"""Backfill service to reconstruct journey-based sessions from historical data.

Reads visits and visit_events (>= 2026-02-01), groups them into journeys
using the same internal/external entry logic as the live tracker, then
rewrites session_id values and rebuilds visit_sessions rows.

Usage:
    from app.services.session_backfill import SessionBackfillService
    svc = SessionBackfillService()
    result = svc.backfill(db, dry_run=True)   # preview
    result = svc.backfill(db, dry_run=False)  # apply
"""

import hashlib
import json
import os
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from sqlalchemy import text, func
from sqlalchemy.orm import Session
import structlog

from app.database import SessionLocal
from app.models.visit import Visit, VisitSession, VisitEvent
from app.utils.domains import is_internal_domain

logger = structlog.get_logger()

# Records before this date are left untouched.
BACKFILL_START = datetime(2026, 2, 1, tzinfo=timezone.utc)

# When two events from different cid families are within this window and
# the transition looks internal, they may be stitched into one journey.
CROSS_FAMILY_MAX_GAP = timedelta(minutes=5)


class SessionBackfillService:
    """Reconstruct journey-based session IDs from historical visit data."""

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def backfill(
        self,
        db: Session,
        dry_run: bool = True,
        batch_size: int = 500,
    ) -> Dict:
        """Run the full backfill pipeline.

        Args:
            db: SQLAlchemy session.
            dry_run: If True, compute new sessions but do NOT write changes.
            batch_size: Commit interval for writes.

        Returns a summary dict.
        """
        logger.info("Session backfill starting", dry_run=dry_run)
        try:
            db.execute(text("SET statement_timeout = 600000"))  # 10 min
            db.execute(text("SET work_mem = '32MB'"))
        except Exception:
            pass

        # Try to load a cached plan from disk (avoids re-running the slow
        # plan phase after crashes).
        cache_path = os.path.join(os.path.dirname(__file__), ".backfill_plan_cache.json")
        migration_plan = self._load_plan_cache(cache_path)

        if migration_plan:
            logger.info("Loaded plan from cache", visits=migration_plan["visits_remapped"],
                        events=migration_plan["events_remapped"])
        else:
            migration_plan = self._stream_build_plan(db)
            # Cache to disk so we never have to recompute
            self._save_plan_cache(cache_path, migration_plan)
            logger.info("Plan cached to disk", path=cache_path)

        stats = {
            "users_processed": migration_plan["users_processed"],
            "sessions_before": migration_plan["sessions_before"],
            "sessions_after": migration_plan["sessions_after"],
            "visits_remapped": migration_plan["visits_remapped"],
            "events_remapped": migration_plan["events_remapped"],
            "audit_rows": len(migration_plan["audit_log"]),
            "dry_run": dry_run,
        }
        logger.info("Backfill plan ready", **stats)

        if dry_run:
            return stats

        # Apply changes
        self._apply_migration(db, migration_plan, batch_size)

        # Remove cache after successful completion
        if os.path.exists(cache_path):
            os.remove(cache_path)

        stats["applied"] = True
        logger.info("Session backfill complete", **stats)
        return stats

    def resume(self, db: Session, batch_size: int = 500) -> Dict:
        """Resume a previously interrupted backfill.

        Skips the plan phase entirely.  Processes any existing staging
        tables (_backfill_remap_*), runs non-entry event sync, rebuilds
        indexes, and cleans up.
        """
        logger.info("Session backfill RESUME starting")
        try:
            db.execute(text("SET statement_timeout = 600000"))
            db.execute(text("SET work_mem = '32MB'"))
        except Exception:
            pass

        # Ensure indexes are dropped (may already be from previous run)
        logger.info("Ensuring session_id indexes are dropped")
        db.execute(text("DROP INDEX IF EXISTS ix_visits_session_id"))
        db.execute(text("DROP INDEX IF EXISTS ix_visit_events_session_id"))
        db.commit()

        # Process any existing staging tables (resumes from where it left off)
        self._remap_via_temp_table(
            db, "visits", "id", {}, batch_size=5000, label="visits"
        )
        self._remap_via_temp_table(
            db, "visit_events", "id", {}, batch_size=5000, label="events"
        )

        # Sync non-entry events
        logger.info("Syncing non-entry event sessions via visit_id")
        sync_start = BACKFILL_START
        sync_now = datetime.now(tz=timezone.utc)
        synced_total = 0
        while sync_start < sync_now:
            sync_end = min(sync_start + self._LOAD_WINDOW, sync_now)
            result = db.execute(text(
                "UPDATE visit_events e "
                "SET session_id = v.session_id "
                "FROM visits v "
                "WHERE e.visit_id = v.id "
                "AND e.visit_id IS NOT NULL "
                "AND e.session_id IS DISTINCT FROM v.session_id "
                "AND e.timestamp >= :start AND e.timestamp < :end"
            ), {"start": sync_start, "end": sync_end})
            synced_total += result.rowcount
            db.commit()
            sync_start = sync_end
        logger.info("Non-entry events synced via visit_id", count=synced_total)

        # Rebuild indexes
        logger.info("Rebuilding session_id indexes")
        db.commit()
        raw_conn = db.get_bind().raw_connection()
        raw_conn.set_session(autocommit=True)
        try:
            cur = raw_conn.cursor()
            cur.execute(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_visits_session_id "
                "ON visits (session_id)"
            )
            cur.execute(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_visit_events_session_id "
                "ON visit_events (session_id)"
            )
            cur.close()
        finally:
            raw_conn.set_session(autocommit=False)
        logger.info("Session_id indexes rebuilt")

        # Cleanup orphaned sessions
        logger.info("Cleaning up orphaned sessions")
        result = db.execute(text(
            "DELETE FROM visit_sessions vs "
            "WHERE NOT EXISTS (SELECT 1 FROM visits v WHERE v.session_id = vs.id) "
            "AND NOT EXISTS (SELECT 1 FROM visit_events e WHERE e.session_id = vs.id) "
            "AND vs.first_visit >= :cutoff"
        ), {"cutoff": BACKFILL_START})
        db.commit()
        logger.info("Orphaned sessions deleted", count=result.rowcount)

        logger.info("Session backfill resume complete")
        return {"resumed": True, "events_synced": synced_total}

    # ------------------------------------------------------------------
    # Streaming load + compute (fused pipeline)
    # ------------------------------------------------------------------

    # How wide each time-range page is when loading records.  Keeps
    # individual queries small so the remote Postgres doesn't OOM.
    _LOAD_WINDOW = timedelta(days=1)

    def _stream_build_plan(self, db: Session) -> Dict:
        """Load records in weekly windows and compute the migration plan.

        Only one window's worth of records lives in memory at a time.
        Per-user session state carries forward across windows, and the
        output maps (visit_updates, event_updates, new_sessions) accumulate
        incrementally — they are much smaller per-entry than full records.
        """
        # Per-user carry-forward state (journey_seq, current session id/meta)
        user_state: Dict[str, dict] = {}

        # Output accumulators
        visit_updates: Dict[int, str] = {}
        event_updates: Dict[int, str] = {}
        new_sessions: Dict[str, dict] = {}
        audit_pairs: Dict[Tuple[str, str], dict] = {}
        old_session_ids: set = set()
        new_session_ids: set = set()

        now = datetime.now(tz=timezone.utc)
        window_start = BACKFILL_START
        window_num = 0

        while window_start < now:
            window_end = min(window_start + self._LOAD_WINDOW, now)
            window_num += 1
            logger.info(
                "Processing window",
                window=window_num,
                start=window_start.isoformat(),
                end=window_end.isoformat(),
            )

            # Load this window's records, with reconnect on failure
            window_records = None
            for attempt in range(3):
                try:
                    window_records = self._load_window(db, window_start, window_end)
                    break
                except Exception as e:
                    logger.warning("Window load failed, reconnecting",
                                   window=window_num, attempt=attempt + 1, error=str(e)[:100])
                    try:
                        db.close()
                    except Exception:
                        pass
                    import time
                    time.sleep(5 * (attempt + 1))
                    db = SessionLocal()
                    try:
                        db.execute(text("SET statement_timeout = 600000"))
                        db.execute(text("SET work_mem = '32MB'"))
                    except Exception:
                        pass
            if window_records is None:
                raise RuntimeError(f"Failed to load window {window_num} after 3 attempts")

            # Process each user's records for this window
            for user_key, records in window_records.items():
                records.sort(
                    key=lambda r: r["timestamp"] or datetime.min.replace(tzinfo=timezone.utc)
                )

                state = user_state.get(user_key)
                if state is None:
                    state = {
                        "journey_seq": 0,
                        "current_session_id": None,
                        "current_session_meta": None,
                    }
                    user_state[user_key] = state

                journey_seq = state["journey_seq"]
                current_session_id = state["current_session_id"]
                current_session_meta = state["current_session_meta"]

                for rec in records:
                    old_session_ids.add(rec["old_session_id"])

                    is_new_journey = self._should_start_new_journey(
                        rec, current_session_meta
                    )

                    if is_new_journey or current_session_id is None:
                        current_session_id = self._make_session_id(
                            user_key, journey_seq
                        )
                        current_session_meta = {
                            "session_id": current_session_id,
                            "user_key": user_key,
                            "client_id": rec.get("client_id"),
                            "ip_address": rec.get("ip_address"),
                            "user_agent": rec.get("user_agent"),
                            "first_visit": rec["timestamp"],
                            "last_visit": rec["timestamp"],
                            "entry_referrer": rec.get("referrer"),
                            "entry_referrer_domain": rec.get("referrer_domain"),
                            "is_external_entry": is_new_journey,
                            "visit_count": 0,
                        }
                        new_sessions[current_session_id] = current_session_meta
                        journey_seq += 1

                    # Carry forward fields that were missing at journey start
                    current_session_meta["last_visit"] = rec["timestamp"]
                    for field in ("client_id", "ip_address", "user_agent"):
                        if rec.get(field) and not current_session_meta.get(field):
                            current_session_meta[field] = rec[field]

                    new_session_ids.add(current_session_id)

                    if rec["old_session_id"] != current_session_id:
                        if rec["type"] == "visit":
                            visit_updates[rec["id"]] = current_session_id
                        else:
                            event_updates[rec["id"]] = current_session_id

                        pair_key = (rec["old_session_id"], current_session_id)
                        if pair_key not in audit_pairs:
                            audit_pairs[pair_key] = {
                                "client_id": None,
                                "visits": 0,
                                "events": 0,
                            }
                        pair = audit_pairs[pair_key]
                        pair["client_id"] = rec.get("client_id")
                        if rec["type"] == "visit":
                            pair["visits"] += 1
                        else:
                            pair["events"] += 1

                    current_session_meta["visit_count"] += 1

                # Save state back for next window
                state["journey_seq"] = journey_seq
                state["current_session_id"] = current_session_id
                state["current_session_meta"] = current_session_meta

            # window_records is discarded here — GC reclaims the memory
            # before the next window is loaded.
            window_start = window_end

        logger.info(
            "Stream processing complete", users=len(user_state), windows=window_num
        )

        audit_log = [
            {
                "old_session_id": old_sid,
                "new_session_id": new_sid,
                "client_id": info["client_id"],
                "visit_count_moved": info["visits"],
                "event_count_moved": info["events"],
            }
            for (old_sid, new_sid), info in audit_pairs.items()
        ]

        return {
            "visit_updates": visit_updates,
            "event_updates": event_updates,
            "new_sessions": new_sessions,
            "audit_log": audit_log,
            "sessions_before": len(old_session_ids),
            "sessions_after": len(new_session_ids),
            "visits_remapped": len(visit_updates),
            "events_remapped": len(event_updates),
            "users_processed": len(user_state),
        }

    _PAGE_SIZE = 2000

    def _load_window(
        self, db: Session, window_start: datetime, window_end: datetime
    ) -> Dict[str, List[dict]]:
        """Load one time window of visits + events, grouped by user key.

        Uses raw SQL with keyset pagination (id > last_id LIMIT N) so each
        query is small and fully closed before the next one starts — no
        lingering cursors or DB-side state accumulation.
        """
        user_records: Dict[str, List[dict]] = defaultdict(list)

        # -- Visits (keyset pagination by id) --
        visit_count = 0
        last_id = 0
        while True:
            rows = db.execute(text(
                "SELECT id, session_id, client_id, ip_address, user_agent, "
                "timestamp, page_url, page_domain, referrer, source, medium, campaign "
                "FROM visits "
                "WHERE timestamp >= :start AND timestamp < :end AND id > :last_id "
                "ORDER BY id LIMIT :lim"
            ), {"start": window_start, "end": window_end, "last_id": last_id,
                "lim": self._PAGE_SIZE}).fetchall()
            if not rows:
                break
            for r in rows:
                rec = {
                    "type": "visit",
                    "id": r[0],
                    "old_session_id": r[1],
                    "client_id": r[2],
                    "ip_address": r[3],
                    "user_agent": (r[4] or "")[:500],
                    "timestamp": r[5],
                    "page_url": r[6],
                    "page_domain": r[7],
                    "referrer": r[8],
                    "referrer_domain": self._extract_domain(r[8]),
                    "source": r[9],
                    "medium": r[10],
                    "campaign": r[11],
                }
                user_records[self._user_key(rec)].append(rec)
            visit_count += len(rows)
            last_id = rows[-1][0]

        # -- Entry-type events only (keyset pagination by id) --
        # Non-entry events (clicks, scrolls, heartbeats) can never affect
        # session boundaries — they're bulk-synced via visit_id FK in
        # _apply_migration instead.
        event_count = 0
        last_id = 0
        while True:
            rows = db.execute(text(
                "SELECT id, session_id, client_id, timestamp, event_type, "
                "page_url, page_domain, referrer, referrer_domain, source, medium, campaign "
                "FROM visit_events "
                "WHERE timestamp >= :start AND timestamp < :end AND id > :last_id "
                "AND client_id IS NOT NULL AND client_id != '' "
                "AND event_type IN :entry_types "
                "ORDER BY id LIMIT :lim"
            ), {"start": window_start, "end": window_end, "last_id": last_id,
                "lim": self._PAGE_SIZE,
                "entry_types": tuple(self._ENTRY_EVENT_TYPES)}).fetchall()
            if not rows:
                break
            for r in rows:
                rec = {
                    "type": "event",
                    "id": r[0],
                    "old_session_id": r[1],
                    "client_id": r[2],
                    "ip_address": None,
                    "user_agent": None,
                    "timestamp": r[3],
                    "event_type": r[4],
                    "page_url": r[5],
                    "page_domain": r[6],
                    "referrer": r[7],
                    "referrer_domain": r[8],
                    "source": r[9],
                    "medium": r[10],
                    "campaign": r[11],
                }
                user_records[self._user_key(rec)].append(rec)
            event_count += len(rows)
            last_id = rows[-1][0]

        logger.info("Window loaded", visits=visit_count, events=event_count)
        return dict(user_records)

    # ------------------------------------------------------------------
    # Session boundary detection
    # ------------------------------------------------------------------

    # Event types that can represent a new page entry.
    # Everything else (click, scroll, form_input, heartbeat, visibility, etc.)
    # is always a continuation of an existing page — never a session boundary.
    _ENTRY_EVENT_TYPES = {"page_view", "navigation", "navigate"}

    # If there's no referrer signal at all and the gap since the last
    # activity exceeds this threshold, treat it as a new journey.
    _INACTIVITY_TIMEOUT = timedelta(minutes=30)

    def _should_start_new_journey(self, rec: dict, current_meta: Optional[dict]) -> bool:
        """Decide whether this historical record starts a new journey.

        Rules (in order):
        1. First record for a user → new journey.
        2. Non-entry events (clicks, scrolls, heartbeats) → always continue.
        3. External referrer → new journey.
        4. Internal referrer → continue (regardless of time gap).
        5. External source/medium/campaign → new journey.
        6. Internal source → continue.
        7. Zero signal + >30 min inactivity → new journey.
        8. Zero signal + <=30 min gap → continue.
        """
        if current_meta is None:
            return True  # very first record for this user

        event_type = rec.get("event_type")
        rec_type = rec.get("type")  # "visit" or "event"

        # Visit records (from the visits table) are always page entries
        is_entry_event = rec_type == "visit" or event_type in self._ENTRY_EVENT_TYPES

        # Non-entry events (clicks, scrolls, heartbeats, form_input, etc.)
        # are always continuations — they cannot start a new journey
        if not is_entry_event:
            return False

        referrer_domain = rec.get("referrer_domain")
        source = rec.get("source")
        medium = rec.get("medium")
        campaign = rec.get("campaign")

        # Referrer domain is the strongest signal
        if referrer_domain:
            if is_internal_domain(referrer_domain):
                return False  # internal referrer → continue regardless of gap
            return True  # external referrer → new journey

        # No referrer — check source/medium/campaign fallbacks
        if source:
            src_lower = source.lower()
            if is_internal_domain(src_lower):
                return False
            return True

        if medium or campaign:
            return True

        # Zero signal — use inactivity timeout as fallback.
        # No referrer + gap > 30 min = likely a new visit (bookmark,
        # typed URL, reopened tab). Short gaps are continuations.
        last_visit = current_meta.get("last_visit")
        rec_ts = rec.get("timestamp")
        if last_visit and rec_ts:
            gap = rec_ts - last_visit
            if gap > self._INACTIVITY_TIMEOUT:
                return True

        return False

    # ------------------------------------------------------------------
    # Apply the migration
    # ------------------------------------------------------------------

    def _apply_migration(self, db: Session, plan: Dict, batch_size: int) -> None:
        """Write new session rows, remap visit/event session_ids, log audit."""
        visit_updates = plan["visit_updates"]
        event_updates = plan["event_updates"]
        new_sessions = plan["new_sessions"]
        audit_log = plan["audit_log"]

        # 6a. Bulk-insert new session rows via raw SQL (avoids per-row ORM overhead).
        # First, find which session IDs already exist so we can skip them.
        all_new_sids = list(new_sessions.keys())
        logger.info("Creating new session rows", count=len(all_new_sids))

        existing_sids: set = set()
        for i in range(0, len(all_new_sids), 5000):
            chunk = all_new_sids[i:i+5000]
            rows = db.execute(
                text("SELECT id FROM visit_sessions WHERE id = ANY(:ids)"),
                {"ids": chunk},
            ).fetchall()
            existing_sids.update(r[0] for r in rows)
        logger.info("Existing sessions found", count=len(existing_sids))

        # Build flat list of rows to insert
        to_insert = []
        for sid, meta in new_sessions.items():
            if sid in existing_sids:
                continue
            to_insert.append((
                sid,
                meta.get("ip_address") or "unknown",
                (meta.get("user_agent") or "unknown")[:500],
                meta.get("client_id"),
                meta.get("first_visit"),
                meta.get("last_visit"),
                meta.get("visit_count", 0),
                (meta.get("entry_referrer") or "")[:2000] or None,
                meta.get("entry_referrer_domain"),
                meta.get("is_external_entry", True),
            ))

        created = 0
        skipped = 0
        for i in range(0, len(to_insert), batch_size):
            chunk = to_insert[i:i+batch_size]
            params = {}
            values_parts = []
            for j, row in enumerate(chunk):
                keys = [f"id{j}", f"ip{j}", f"ua{j}", f"cid{j}", f"fv{j}", f"lv{j}",
                        f"vc{j}", f"er{j}", f"erd{j}", f"ie{j}"]
                for k, val in zip(keys, row):
                    params[k] = val
                values_parts.append(
                    f"(:{keys[0]}, :{keys[1]}, :{keys[2]}, :{keys[3]}, :{keys[4]}, "
                    f":{keys[5]}, :{keys[6]}, :{keys[7]}, :{keys[8]}, :{keys[9]})"
                )
            sql = (
                "INSERT INTO visit_sessions "
                "(id, ip_address, user_agent, client_id, first_visit, last_visit, "
                "visit_count, entry_referrer, entry_referrer_domain, is_external_entry) "
                f"VALUES {','.join(values_parts)} "
                "ON CONFLICT (id) DO NOTHING"
            )
            try:
                db.execute(text(sql), params)
                db.commit()
                created += len(chunk)
            except Exception as e:
                db.rollback()
                skipped += len(chunk)
                if skipped <= 2500:
                    logger.warning("Batch insert failed", error=str(e)[:200])

            if (i // batch_size) % 20 == 0:
                logger.info("Sessions insert progress", done=min(i + batch_size, len(to_insert)), total=len(to_insert))
        logger.info("Session rows created", created=created, skipped=skipped)

        # 5a. Remap visits — VALUES-join update (constant time per batch,
        # unlike the old CASE approach which degraded as the transaction grew).
        logger.info("Remapping visits", count=len(visit_updates))
        visit_items = list(visit_updates.items())
        for i in range(0, len(visit_items), batch_size):
            chunk = visit_items[i:i+batch_size]
            params = {}
            values_parts = []
            for j, (vid, new_sid) in enumerate(chunk):
                params[f"v{j}"] = vid
                params[f"s{j}"] = new_sid
                values_parts.append(f"(:v{j}, :s{j})")
            sql = (
                f"UPDATE visits SET session_id = _map.new_sid "
                f"FROM (VALUES {','.join(values_parts)}) AS _map(vid, new_sid) "
                f"WHERE visits.id = _map.vid"
            )
            db.execute(text(sql), params)
            db.commit()
            if (i // batch_size) % 20 == 0:
                logger.info("Visits remapped progress", done=min(i + batch_size, len(visit_items)), total=len(visit_items))
        logger.info("Visits remapped done")

        # 5b. Remap events — same VALUES-join approach
        old_to_new_session: Dict[str, str] = {}
        for entry in audit_log:
            old_to_new_session[entry["old_session_id"]] = entry["new_session_id"]

        logger.info("Remapping events by session_id", mappings=len(old_to_new_session))
        mapping_items = list(old_to_new_session.items())
        for i in range(0, len(mapping_items), batch_size):
            chunk = mapping_items[i:i+batch_size]
            params = {}
            values_parts = []
            for j, (old_sid, new_sid) in enumerate(chunk):
                params[f"o{j}"] = old_sid
                params[f"n{j}"] = new_sid
                values_parts.append(f"(:o{j}, :n{j})")
            sql = (
                f"UPDATE visit_events SET session_id = _map.new_sid "
                f"FROM (VALUES {','.join(values_parts)}) AS _map(old_sid, new_sid) "
                f"WHERE visit_events.session_id = _map.old_sid"
            )
            db.execute(text(sql), params)
            db.commit()
            if (i // batch_size) % 20 == 0:
                logger.info("Events remapped progress", done=min(i + batch_size, len(mapping_items)), total=len(mapping_items))
        logger.info("Events remapped done")

        # 6b. Write audit log
        logger.info("Writing audit log", rows=len(audit_log))
        for i in range(0, len(audit_log), batch_size):
            chunk = audit_log[i:i+batch_size]
            params = {}
            values_parts = []
            for j, entry in enumerate(chunk):
                params[f"o{j}"] = entry["old_session_id"]
                params[f"n{j}"] = entry["new_session_id"]
                params[f"c{j}"] = entry.get("client_id")
                params[f"vc{j}"] = entry.get("visit_count_moved", 0)
                params[f"ec{j}"] = entry.get("event_count_moved", 0)
                values_parts.append(f"(:o{j}, :n{j}, :c{j}, :vc{j}, :ec{j})")
            sql = (
                "INSERT INTO session_id_migration_log "
                "(old_session_id, new_session_id, client_id, visit_count_moved, event_count_moved) "
                f"VALUES {','.join(values_parts)}"
            )
            db.execute(text(sql), params)
            db.commit()
            if (i // batch_size) % 20 == 0:
                logger.info("Audit log progress", done=min(i + batch_size, len(audit_log)), total=len(audit_log))
        logger.info("Audit log done")

        # 7. Delete orphaned session rows — both remapped old sessions and
        #    any sessions with no visits/events (e.g. from dedup race conditions)
        old_sids_to_delete = [
            entry["old_session_id"]
            for entry in audit_log
            if entry["old_session_id"] != entry["new_session_id"]
        ]
        logger.info("Cleaning up remapped session rows", count=len(old_sids_to_delete))
        deleted_remapped = 0
        for i in range(0, len(old_sids_to_delete), batch_size):
            chunk = old_sids_to_delete[i:i+batch_size]
            params = {f"s{j}": sid for j, sid in enumerate(chunk)}
            placeholders = ",".join(f":s{j}" for j in range(len(chunk)))
            sql = (
                f"DELETE FROM visit_sessions WHERE id IN ({placeholders}) "
                f"AND NOT EXISTS (SELECT 1 FROM visits WHERE session_id = visit_sessions.id) "
                f"AND NOT EXISTS (SELECT 1 FROM visit_events WHERE session_id = visit_sessions.id)"
            )
            result = db.execute(text(sql), params)
            deleted_remapped += result.rowcount
            db.commit()
        logger.info("Remapped session rows deleted", deleted=deleted_remapped,
                     skipped=len(old_sids_to_delete) - deleted_remapped)

        # 7b. Clean up any other orphaned sessions (visit_count=0, no references)
        result = db.execute(text(
            "DELETE FROM visit_sessions "
            "WHERE visit_count = 0 "
            "AND NOT EXISTS (SELECT 1 FROM visits WHERE session_id = visit_sessions.id) "
            "AND NOT EXISTS (SELECT 1 FROM visit_events WHERE session_id = visit_sessions.id)"
        ))
        deleted_orphans = result.rowcount
        db.commit()
        logger.info("Orphaned session rows deleted", deleted=deleted_orphans)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _user_key(rec: dict) -> str:
        """Best-effort user identity key for grouping.

        Prefers client_id; falls back to ip+ua hash.
        """
        cid = rec.get("client_id")
        if cid:
            return f"cid:{cid}"
        ip = rec.get("ip_address", "")
        ua = (rec.get("user_agent") or "")[:500]
        return f"ipua:{ip}:{ua}"

    @staticmethod
    def _make_session_id(user_key: str, journey_seq: int) -> str:
        """Deterministic session ID from user key + journey sequence.

        Same scheme as TrackingService._generate_session_id.
        """
        data = f"{user_key}:journey:{journey_seq}"
        return hashlib.sha256(data.encode()).hexdigest()[:32]

    @staticmethod
    def _extract_domain(url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        try:
            return urlparse(url).netloc or None
        except Exception:
            return None


