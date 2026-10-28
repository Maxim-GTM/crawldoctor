"""IP enrichment service — persists company-level data for visitor IPs."""
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Optional
import httpx
import structlog
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.background.models import BackgroundJobState
from app.config import settings
from app.models.enrichment import IpEnrichment

logger = structlog.get_logger()

_PROVIDER = "ipapi.is"
_API_BASE = "https://api.ipapi.is"

# Without a key ipapi.is allows 30 lookups per server IP per UTC day (since 2026-09-01).
_ANONYMOUS_DAILY_LIMIT = 25
# Transient errors wait retry_base * 2^(attempts - 1) before the next try, up to this.
_MAX_RETRY_WAIT = timedelta(days=7)
_MAX_DOUBLINGS = 20  # keeps 2^n finite for rows with thousands of attempts
# background_job_state row holding the time until which no lookups are sent.
_PAUSE_KEY = "ip_enrichment:paused_until"
# Advisory lock so two app workers never send the same batch twice.
_BATCH_LOCK_ID = 0x1E_E1C4
_NO_LOCK = object()  # stands in for the lock connection on databases without advisory locks


class PermanentLookupError(Exception):
    """The provider rejected this IP (4xx other than 401/403/429). Not retried."""


class TransientLookupError(Exception):
    """This lookup failed (timeout, 5xx, unreadable answer). Retried with backoff."""


class ProviderUnavailable(Exception):
    """The provider refused service for every IP, so the batch stops.

    record_ip: also record an error against the IP being looked up, so a refusal that is
    really about that IP can't block the head of the queue forever.
    pause_until: send nothing before this time.
    """

    def __init__(self, reason: str, pause_until: Optional[datetime] = None, record_ip: bool = False):
        super().__init__(reason)
        self.reason = reason
        self.pause_until = pause_until
        self.record_ip = record_ip


def _next_utc_midnight(now: datetime) -> datetime:
    return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def retry_wait(attempts: int) -> timedelta:
    """How long to wait after the n-th consecutive transient error."""
    base = timedelta(minutes=settings.ip_enrichment_retry_base_minutes)
    return min(base * (2 ** min(max(attempts - 1, 0), _MAX_DOUBLINGS)), _MAX_RETRY_WAIT)


def priority_path_regex(paths: list[str]) -> str:
    """Postgres regex matching any of `paths` as whole path segments (so /bifrost/pricing counts)."""
    parts = [re.escape(p.strip("/")) for p in paths if p.strip("/")]
    return "(^|/)(" + "|".join(parts) + ")(/|$)" if parts else "$^"


class IpEnrichmentService:
    """Enriches visitor IPs with company identity and network flags.

    Uses ipapi.is. With CRAWLDOCTOR_IP_ENRICHMENT_API_KEY (a free account gives 1,000 lookups
    a day) the answer has the company object (name, domain, type), location and network flags.
    Without a key it is capped at 30 lookups a day per server IP and has only the company name.
    """

    def _clean_str(self, val) -> Optional[str]:
        if val is None:
            return None
        s = str(val).strip().lower()
        if s in ("", "nan", "null", "none", "n/a", "unknown"):
            return None
        return s

    def _clean_str_raw(self, val) -> Optional[str]:
        """Same as _clean_str but preserves original casing."""
        if val is None:
            return None
        s = str(val).strip()
        if s.lower() in ("", "nan", "null", "none", "n/a", "unknown"):
            return None
        return s

    def _country_code(self, raw: dict) -> Optional[str]:
        location = raw.get("location") if isinstance(raw.get("location"), dict) else {}
        for val in (location.get("country_code"), raw.get("country_code"), raw.get("country")):
            code = self._clean_str(val)
            if code and len(code) == 2 and code.isalpha():
                return code
        return None

    def _flag(self, raw: dict, key: str) -> Optional[bool]:
        val = raw.get(key)
        return val if isinstance(val, bool) else None

    def _normalize(self, ip: str, raw: dict, first_seen_at, last_seen_at) -> dict:
        """Map an ipapi.is answer to ip_enrichment columns.

        The keyed answer has `company` as an object; the anonymous one (since 2026-09-01) has it
        as the organisation name and no network flags.
        """
        now = datetime.now(timezone.utc)
        company = raw.get("company")
        if isinstance(company, dict):
            name, domain, kind = company.get("name"), company.get("domain"), company.get("type")
        else:
            name, domain, kind = company, None, None

        return {
            "ip": ip,
            "company_domain": self._clean_str(domain),
            "company_name": self._clean_str_raw(name),
            "company_type": self._clean_str(kind),
            "country": self._country_code(raw),
            "is_datacenter": self._flag(raw, "is_datacenter"),
            "is_vpn": self._flag(raw, "is_vpn"),
            "is_proxy": self._flag(raw, "is_proxy"),
            "is_tor": self._flag(raw, "is_tor"),
            "source": _PROVIDER,
            "enriched_at": now,
            "ttl_expires_at": now + timedelta(days=settings.ip_enrichment_ttl_days),
            "status": "success",
            "error_code": None,
            "error_message": None,
            "attempt_count": 0,
            "first_seen_at": first_seen_at,
            "last_seen_at": last_seen_at,
        }

    def _http_client(self) -> httpx.Client:
        return httpx.Client(timeout=httpx.Timeout(10.0))

    def _call_api(self, ip: str, client: httpx.Client) -> dict:
        """Look up one IP. One request, no retries: retries are scheduled through the table.

        The key goes in the POST body, which keeps it out of URLs and logs.
        """
        body = {"q": ip}
        if settings.ip_enrichment_api_key:
            body["key"] = settings.ip_enrichment_api_key
        now = datetime.now(timezone.utc)

        try:
            resp = client.post(_API_BASE, json=body)
        except httpx.ConnectError as exc:
            # ipapi.is firewalls clients that keep sending after a 429 for 24 hours. A refused
            # connection is that block (or an outage): wait it out instead of probing hourly.
            raise ProviderUnavailable(f"connect failed: {exc}", pause_until=now + timedelta(hours=24))
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            raise TransientLookupError(f"{type(exc).__name__}: {exc}")

        status = resp.status_code
        if status == 200:
            try:
                raw = resp.json()
            except ValueError:
                raise TransientLookupError(f"unreadable answer: {resp.text[:200]}")
            if not isinstance(raw, dict) or ("error" in raw and "ip" not in raw):
                raise TransientLookupError(f"unexpected answer: {str(raw)[:200]}")
            return raw
        if status == 429:
            # Daily quota used up. It resets at midnight UTC; sending more gets the IP firewalled.
            raise ProviderUnavailable(f"HTTP 429: {resp.text[:200]}", pause_until=_next_utc_midnight(now))
        if status in (401, 403):
            raise ProviderUnavailable(f"HTTP {status}: {resp.text[:200]}", record_ip=True)
        if status >= 500:
            raise TransientLookupError(f"HTTP {status}: {resp.text[:200]}")
        raise PermanentLookupError(f"HTTP {status}: {resp.text[:200]}")

    def _get_candidates(self, db: Session, batch_size: int) -> list[dict]:
        """IPs that need a lookup, most valuable first.

        Only human visitors seen in the last ip_enrichment_lookback_days. Order: IPs of leads,
        then IPs that viewed a priority page (pricing, enterprise, demo, contact), then the most
        recently seen. Eligible: never looked up, success past its TTL, transient errors whose
        backoff has elapsed, and rows the old 3-attempt cap marked failed for transient errors.
        """
        rows = db.execute(text("""
            WITH recent AS (
                SELECT v.ip_address AS ip,
                       MIN(v.timestamp) AS first_seen_at,
                       MAX(v.timestamp) AS last_seen_at,
                       BOOL_OR(ls.client_id IS NOT NULL) AS is_lead,
                       BOOL_OR(COALESCE(v.path, '') ~ :priority_re) AS high_intent
                FROM visits v
                LEFT JOIN lead_summaries ls ON ls.client_id = v.client_id
                WHERE v.is_bot = false
                  AND v.timestamp >= now() - make_interval(days => :lookback_days)
                  AND v.ip_address IS NOT NULL
                  AND v.ip_address NOT IN ('127.0.0.1', '::1', '')
                GROUP BY v.ip_address
            )
            SELECT r.ip, r.first_seen_at, r.last_seen_at, r.is_lead, r.high_intent
            FROM recent r
            LEFT JOIN ip_enrichment e ON e.ip = r.ip
            WHERE e.ip IS NULL
               OR e.status = 'pending'
               OR (e.status = 'success' AND e.ttl_expires_at <= now())
               OR (e.status = 'failed' AND e.error_code = 'transient')
               OR (e.status = 'error' AND e.enriched_at <= now() - make_interval(
                       mins => LEAST(:retry_base * power(2, LEAST(GREATEST(e.attempt_count - 1, 0),
                                                                  :max_doublings)),
                                     :retry_max)::int))
            ORDER BY r.is_lead DESC, r.high_intent DESC, r.last_seen_at DESC
            LIMIT :batch_size
        """), {
            "batch_size": batch_size,
            "lookback_days": settings.ip_enrichment_lookback_days,
            "priority_re": priority_path_regex(settings.ip_enrichment_priority_paths),
            "retry_base": settings.ip_enrichment_retry_base_minutes,
            "retry_max": int(_MAX_RETRY_WAIT.total_seconds() // 60),
            "max_doublings": _MAX_DOUBLINGS,
        }).fetchall()

        return [
            {"ip": r.ip, "first_seen_at": r.first_seen_at, "last_seen_at": r.last_seen_at}
            for r in rows
        ]

    def _daily_limit(self) -> int:
        if settings.ip_enrichment_api_key:
            return settings.ip_enrichment_daily_limit
        return min(settings.ip_enrichment_daily_limit, _ANONYMOUS_DAILY_LIMIT)

    def _lookups_today(self, db: Session) -> int:
        """Lookups answered today (UTC): every answer, good or bad, rewrites enriched_at."""
        midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        return db.query(IpEnrichment).filter(IpEnrichment.enriched_at >= midnight).count()

    def _paused_until(self, db: Session) -> Optional[datetime]:
        row = db.get(BackgroundJobState, _PAUSE_KEY)
        if not row:
            return None
        until = row.last_processed_at
        return until.replace(tzinfo=timezone.utc) if until.tzinfo is None else until

    def _pause(self, db: Session, until: datetime) -> None:
        row = db.get(BackgroundJobState, _PAUSE_KEY)
        if row:
            row.last_processed_at = until
        else:
            db.add(BackgroundJobState(job_name=_PAUSE_KEY, last_processed_at=until))
        db.commit()

    def _try_lock(self, db: Session):
        """Take the batch lock on a connection of its own; returns it, or None if another worker has it.

        Not on the Session's connection: the Session hands that back to the pool on every
        commit, and an unlock sent on a different connection would leave the lock held.
        """
        bind = db.get_bind()
        if bind.dialect.name != "postgresql":
            return _NO_LOCK
        conn = bind.connect()
        acquired = conn.execute(text("SELECT pg_try_advisory_lock(:id)"), {"id": _BATCH_LOCK_ID}).scalar()
        conn.commit()  # a session-level advisory lock outlives the transaction
        if not acquired:
            conn.close()
            return None
        return conn

    def _unlock(self, conn) -> None:
        if conn is _NO_LOCK:
            return
        try:
            conn.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": _BATCH_LOCK_ID})
            conn.commit()
        finally:
            conn.close()

    def _upsert(self, db: Session, data: dict):
        """Write a successful lookup, keeping the earliest first_seen_at."""
        row = db.get(IpEnrichment, data["ip"])
        if row is None:
            db.add(IpEnrichment(**data))
        else:
            first_seen = data["first_seen_at"]
            for key, value in data.items():
                if key not in ("ip", "first_seen_at"):
                    setattr(row, key, value)
            if first_seen and (row.first_seen_at is None or first_seen < row.first_seen_at):
                row.first_seen_at = first_seen
        db.commit()

    def _upsert_error(self, db: Session, ip: str, error_code: str, message: str,
                      first_seen_at, last_seen_at, permanent: bool = False):
        """Record a failed lookup without erasing data from an earlier successful one.

        Transient errors become status 'error' and are retried after retry_wait(attempts);
        permanent ones become 'failed'. A row that already has company data stays 'success'
        and is retried when its new TTL (the backoff) runs out.
        """
        now = datetime.now(timezone.utc)
        row = db.get(IpEnrichment, ip)
        if row is None:
            row = IpEnrichment(ip=ip, source=_PROVIDER, attempt_count=0,
                               first_seen_at=first_seen_at, last_seen_at=last_seen_at)
            db.add(row)
        # Consecutive transient errors under the backoff scheme. Rows the old code marked
        # 'failed' after 3 tries start again from 1.
        previous = (row.attempt_count or 0) if row.status in ("error", "success") else 0
        row.attempt_count = previous + 1
        row.enriched_at = now
        row.last_seen_at = last_seen_at or row.last_seen_at
        row.error_code = error_code[:50] if error_code else None
        row.error_message = message[:500] if message else None
        if row.status == "success" and row.company_name and not permanent:
            row.ttl_expires_at = now + retry_wait(row.attempt_count)
        else:
            row.status = "failed" if permanent else "error"
            row.ttl_expires_at = None
        db.commit()

    def _record_error(self, db: Session, candidate: dict, error_code: str, exc: Exception,
                      permanent: bool = False) -> None:
        try:
            db.rollback()  # clear any failed transaction before writing the error
            self._upsert_error(db, candidate["ip"], error_code, str(exc),
                               candidate["first_seen_at"], candidate["last_seen_at"], permanent)
        except Exception as write_exc:
            logger.error("ip enrichment: failed to record error", ip=candidate["ip"], error=str(write_exc))
            try:
                db.rollback()
            except Exception:
                pass

    def run_batch(self, db: Session, batch_size: Optional[int] = None) -> dict:
        """Enrich one batch of candidate IPs. Returns per-batch stats."""
        if not settings.ip_enrichment_enabled:
            return {"skipped": True, "reason": "ip_enrichment_enabled=false"}

        lock = self._try_lock(db)
        if lock is None:
            return {"skipped": True, "reason": "another worker is running a batch"}
        try:
            return self._run_locked_batch(db, batch_size or settings.ip_enrichment_batch_size)
        finally:
            self._unlock(lock)

    def _run_locked_batch(self, db: Session, batch_size: int) -> dict:
        now = datetime.now(timezone.utc)
        paused_until = self._paused_until(db)
        if paused_until and paused_until > now:
            return {"skipped": True, "reason": "paused", "paused_until": paused_until.isoformat()}

        remaining = self._daily_limit() - self._lookups_today(db)
        if remaining <= 0:
            return {"skipped": True, "reason": "daily limit reached", "daily_limit": self._daily_limit()}

        candidates = self._get_candidates(db, min(batch_size, remaining))

        stats = {"candidates": len(candidates), "success": 0, "error": 0, "failed": 0, "stopped": None}
        min_interval = 1.0 / max(settings.ip_enrichment_max_rps, 0.01)

        with self._http_client() as client:
            for candidate in candidates:
                ip = candidate["ip"]
                t0 = time.monotonic()

                try:
                    raw = self._call_api(ip, client)
                    data = self._normalize(ip, raw, candidate["first_seen_at"], candidate["last_seen_at"])
                    self._upsert(db, data)
                    stats["success"] += 1
                    logger.info("ip enriched", ip=ip, company_domain=data.get("company_domain"))
                except ProviderUnavailable as exc:
                    stats["stopped"] = exc.reason
                    logger.warning("ip enrichment stopped: provider unavailable", ip=ip, reason=exc.reason,
                                   paused_until=exc.pause_until.isoformat() if exc.pause_until else None)
                    if exc.record_ip:
                        stats["error"] += 1
                        self._record_error(db, candidate, "provider_refused", exc)
                    if exc.pause_until:
                        self._pause(db, exc.pause_until)
                    break
                except PermanentLookupError as exc:
                    stats["failed"] += 1
                    logger.warning("ip enrichment permanent failure", ip=ip, error=str(exc))
                    self._record_error(db, candidate, "api_4xx", exc, permanent=True)
                except Exception as exc:
                    # TransientLookupError, or a DB failure on the success path
                    stats["error"] += 1
                    logger.warning("ip enrichment transient error", ip=ip, error=str(exc))
                    self._record_error(db, candidate, "transient", exc)

                # Rate limit: sleep for the remainder of the inter-request interval
                elapsed = time.monotonic() - t0
                remainder = min_interval - elapsed
                if remainder > 0:
                    time.sleep(remainder)

        logger.info("ip enrichment batch complete", **stats)
        return stats

    def run_backfill(self, db: Session, max_batches: int = 10) -> dict:
        """Run multiple batches for initial backfill.

        Each batch respects the daily limit, so this never spends more than the day's quota.
        """
        totals = {"batches": 0, "candidates": 0, "success": 0, "error": 0, "failed": 0, "stopped": None}

        for _ in range(max_batches):
            result = self.run_batch(db)
            if result.get("skipped"):
                totals["stopped"] = result.get("reason")
                break
            totals["batches"] += 1
            totals["candidates"] += result["candidates"]
            totals["success"] += result["success"]
            totals["error"] += result["error"]
            totals["failed"] += result["failed"]
            if result.get("stopped"):
                totals["stopped"] = result["stopped"]
                break
            if result["candidates"] == 0:
                break  # nothing left to enrich

        logger.info("ip enrichment backfill complete", **totals)
        return totals

    def get_coverage_stats(self, db: Session) -> dict:
        """Return enrichment coverage metrics."""
        rows = db.execute(text("""
            SELECT
                COUNT(DISTINCT v.ip_address)                             AS candidates_total,
                COUNT(DISTINCT e.ip) FILTER (WHERE e.status = 'success') AS enriched_success,
                COUNT(DISTINCT e.ip) FILTER (WHERE e.status = 'error')   AS enriched_error,
                COUNT(DISTINCT e.ip) FILTER (WHERE e.status = 'failed')  AS enriched_failed
            FROM visits v
            LEFT JOIN ip_enrichment e ON e.ip = v.ip_address
            WHERE v.is_bot = false
              AND v.ip_address IS NOT NULL
              AND v.ip_address NOT IN ('127.0.0.1', '::1', '')
        """)).fetchone()

        total = rows.candidates_total or 0
        success = rows.enriched_success or 0
        coverage = round(success / total * 100, 1) if total else 0.0

        return {
            "candidates_total": total,
            "enriched_success_total": success,
            "enriched_error_total": rows.enriched_error or 0,
            "enriched_failed_total": rows.enriched_failed or 0,
            "enriched_skipped_total": total - success - (rows.enriched_error or 0) - (rows.enriched_failed or 0),
            "coverage_percent": coverage,
        }
