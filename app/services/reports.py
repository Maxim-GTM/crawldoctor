"""Reports built on top of the raw tables: trends, top pages, channels, AI referrals,
companies, tracking health, filter facets and the dashboard's global search.

Every query on `visits` is bounded by a timestamp range: the table is large and
has no trigram index, so an unbounded ILIKE would scan all of it.
"""
import ipaddress
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from sqlalchemy import and_, case, desc, func, or_, text
from sqlalchemy.orm import Session

from app.models.enrichment import IpEnrichment
from app.models.summary import JourneySummary, LeadSummary
from app.models.visit import Visit, VisitSession
from app.services.channels import (
    AI, AI_ASSISTANT_SOURCES, CHANNELS, DIRECT, REFERRAL, ai_assistant, classify_channel,
)
from app.utils.domains import is_internal_domain


def like_pattern(value: str) -> str:
    """'%value%' with LIKE wildcards in the value escaped (use with escape='\\')."""
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def contains(column, value: str):
    return column.ilike(like_pattern(value), escape="\\")


def bounded(since: Optional[datetime], until: Optional[datetime], default_days: int = 30):
    """The (since, until) a report runs over; a missing start means the last `default_days`."""
    return since or (datetime.now(timezone.utc) - timedelta(days=default_days)), until


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    # SQLite (tests) hands back naive datetimes; Postgres returns them with a zone.
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return _aware(dt).isoformat() if dt else None


def _visitor_key():
    return func.coalesce(Visit.client_id, Visit.session_id)


def _in_range(column, since, until) -> list:
    f = [column >= since]
    if until:
        f.append(column <= until)
    return f


PAIR_SEP = "\x1f"  # joins source and medium into one comparable value

# Values a report should never treat as a site we track
JUNK_DOMAINS = {"gtm-msr.appspot.com", "docs.modrouter.online"}


def is_junk_domain(domain: Optional[str]) -> bool:
    """Local dev servers, raw IPs, odd ports and known test hosts."""
    d = (domain or "").strip().lower()
    if not d or d in JUNK_DOMAINS:
        return True
    host, _, port = d.partition(":")
    if port or host == "localhost" or host.endswith(".localhost") or host.endswith(".invalid"):
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


QUIET_AFTER = timedelta(hours=24)
STALE_AFTER = timedelta(days=7)


def tracking_status(last_seen: Optional[datetime], now: datetime) -> str:
    """'live' (seen in the last day), 'quiet' (in the last week) or 'stale'."""
    if not last_seen:
        return "stale"
    age = now - _aware(last_seen)
    if age <= QUIET_AFTER:
        return "live"
    if age <= STALE_AFTER:
        return "quiet"
    return "stale"


_COMPANY_KEY = re.compile(r"^(company|company[ _-]?name|organi[sz]ation|organi[sz]ation[ _-]?name|business)$", re.I)


def company_from_form(captured_data: Optional[str]) -> Optional[str]:
    """The company a lead typed into a form, if the form asked for one."""
    if not captured_data:
        return None
    try:
        values = json.loads(captured_data)
    except (TypeError, ValueError):
        return None
    if not isinstance(values, dict):
        return None
    for key, value in values.items():
        if _COMPANY_KEY.match(str(key).strip()) and isinstance(value, str) and value.strip():
            return value.strip()[:200]
    return None


def form_answers_match(captured_data: Optional[str], term: str) -> bool:
    """True when `term` is in one of the answers a lead typed, not in the form's questions."""
    if not captured_data:
        return False
    t = term.lower()
    try:
        values = json.loads(captured_data)
    except (TypeError, ValueError):
        return t in captured_data.lower()
    if not isinstance(values, dict):
        return t in str(values).lower()
    return any(t in str(v).lower() for v in values.values() if v is not None)


def lead_matches(lead, term: str) -> bool:
    """A lead summary row matches a search by its email, name, client ID or form answers."""
    t = term.lower()
    return (
        t in (lead.email or "").lower() or t in (lead.name or "").lower()
        or lead.client_id == term or form_answers_match(lead.captured_data, term)
    )


class ReportsService:

    @staticmethod
    def _day(db: Session, column):
        if db.bind.dialect.name == "postgresql":
            return func.date(func.timezone("UTC", column))
        return func.date(column)

    # ---------- Filter facets ----------

    FACETS = {
        "visits.source": (Visit.source, Visit.timestamp),
        "visits.country": (Visit.country, Visit.timestamp),
        "visits.page_domain": (Visit.page_domain, Visit.timestamp),
        "visits.crawler_type": (Visit.crawler_type, Visit.timestamp),
        # Sessions are filtered on last_visit; first_visit is indexed and close enough for suggestions
        "sessions.country": (VisitSession.country, VisitSession.first_visit),
        "sessions.entry_referrer_domain": (VisitSession.entry_referrer_domain, VisitSession.first_visit),
        "leads.captured_path": (LeadSummary.captured_path, LeadSummary.last_seen),
        "leads.source": (LeadSummary.source, LeadSummary.last_seen),
        "journeys.source": (JourneySummary.source, JourneySummary.last_seen),
        "journeys.campaign": (JourneySummary.campaign, JourneySummary.last_seen),
    }

    def facet(self, db: Session, field: str, since=None, until=None, humans_only: bool = False, limit: int = 25) -> Dict[str, Any]:
        """The most common values of one column in the range, for filter suggestions."""
        column, ts = self.FACETS[field]
        since, until = bounded(since, until)
        filters = _in_range(ts, since, until) + [column.isnot(None), column != ""]
        if humans_only and field.startswith("visits."):
            filters.append(Visit.is_bot == False)  # noqa: E712
        rows = (
            db.query(column.label("value"), func.count().label("count"))
            .filter(*filters).group_by(column).order_by(desc("count")).limit(limit).all()
        )
        return {"field": field, "values": [{"value": r.value, "count": r.count} for r in rows]}

    # ---------- Daily trend ----------

    def timeseries(self, db: Session, since=None, until=None) -> Dict[str, Any]:
        """Page views per UTC day and crawler label ("Human" for people); the dashboard groups labels into kinds."""
        since, until = bounded(since, until)
        day = self._day(db, Visit.timestamp)
        # People have no crawler_type (as in the categories endpoint); grouping on it alone lets
        # Postgres answer from the (timestamp, crawler_type) index
        label = func.coalesce(Visit.crawler_type, "Human")
        rows = (
            db.query(day.label("day"), label.label("name"), func.count().label("count"))
            .filter(*_in_range(Visit.timestamp, since, until))
            .group_by(day, label).order_by(day).all()
        )
        return {"series": [{"day": str(r.day), "name": r.name, "count": r.count} for r in rows]}

    # ---------- Top pages ----------

    def top_pages(self, db: Session, since=None, until=None, humans_only: bool = True, domain: Optional[str] = None,
                  path: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
        since, until = bounded(since, until)
        filters = _in_range(Visit.timestamp, since, until) + [Visit.path.isnot(None)]
        if humans_only:
            filters.append(Visit.is_bot == False)  # noqa: E712
        if domain:
            filters.append(Visit.page_domain == domain)
        if path:
            filters.append(contains(Visit.path, path))
        rows = (
            db.query(
                Visit.page_domain, Visit.path,
                func.count(Visit.id).label("views"),
                func.count(func.distinct(_visitor_key())).label("visitors"),
                func.max(Visit.timestamp).label("last_seen"),
            )
            .filter(*filters).group_by(Visit.page_domain, Visit.path).order_by(desc("views")).limit(limit).all()
        )
        return {"pages": [
            {"domain": r.page_domain, "path": r.path, "views": r.views, "visitors": r.visitors, "last_seen": _iso(r.last_seen)}
            for r in rows
        ]}

    # ---------- Channels ----------

    @staticmethod
    def _source_key():
        return func.coalesce(func.lower(Visit.source), ""), func.coalesce(func.lower(Visit.medium), "")

    def channels(self, db: Session, since=None, until=None) -> Dict[str, Any]:
        """Human page views, visitors and leads per channel, with each channel's top sources."""
        since, until = bounded(since, until)
        human = _in_range(Visit.timestamp, since, until) + [Visit.is_bot == False]  # noqa: E712
        src, med = self._source_key()
        pairs = (
            db.query(src.label("source"), med.label("medium"), func.count(Visit.id).label("views"))
            .filter(*human).group_by(src, med).all()
        )
        by_channel: Dict[str, list] = {c: [] for c in CHANNELS}
        for p in pairs:
            by_channel[classify_channel(p.source, p.medium)].append(p)

        # Exact visitor counts need the grouping in SQL: map each (source, medium) pair to its channel.
        # Referral is the fallback, which keeps the long tail of one-off sources out of the CASE.
        pair = src.concat(PAIR_SEP).concat(med)
        whens = [
            (pair.in_([f"{p.source}{PAIR_SEP}{p.medium}" for p in rows]), channel)
            for channel, rows in by_channel.items() if rows and channel != REFERRAL
        ]
        channel_expr = case(*whens, else_=REFERRAL) if whens else None
        visitors: Dict[str, int] = {}
        if channel_expr is not None:
            for r in (
                db.query(channel_expr.label("channel"), func.count(func.distinct(_visitor_key())).label("visitors"))
                .filter(*human).group_by(channel_expr).all()
            ):
                visitors[r.channel] = r.visitors
        elif pairs:
            visitors[REFERRAL] = db.query(func.count(func.distinct(_visitor_key()))).filter(*human).scalar() or 0

        leads: Dict[str, int] = {}
        for s, m in db.query(LeadSummary.source, LeadSummary.medium).filter(*_in_range(LeadSummary.last_seen, since, until)):
            ch = classify_channel(s, m)
            leads[ch] = leads.get(ch, 0) + 1

        out = []
        for channel in CHANNELS:
            rows = sorted(by_channel[channel], key=lambda p: -p.views)
            views = sum(p.views for p in rows)
            if not views and not leads.get(channel):
                continue
            out.append({
                "channel": channel, "views": views, "visitors": visitors.get(channel, 0), "leads": leads.get(channel, 0),
                "sources": [{"source": p.source or "direct", "medium": p.medium or None, "views": p.views} for p in rows[:8]],
            })
        out.sort(key=lambda c: -c["views"])
        return {"channels": out}

    # ---------- AI-assistant referrals ----------

    def ai_referrals(self, db: Session, since=None, until=None) -> Dict[str, Any]:
        """Human page views whose source is an AI assistant, the pages they landed on, and the leads they brought."""
        since, until = bounded(since, until)
        src = func.lower(Visit.source)
        by_name: Dict[str, list] = {}
        for value, name in AI_ASSISTANT_SOURCES.items():
            by_name.setdefault(name, []).append(value)
        assistant = case(*[(src.in_(values), name) for name, values in by_name.items()], else_="Other")
        filters = _in_range(Visit.timestamp, since, until) + [Visit.is_bot == False, src.in_(list(AI_ASSISTANT_SOURCES))]  # noqa: E712

        totals = db.query(func.count(Visit.id), func.count(func.distinct(_visitor_key()))).filter(*filters).one()
        assistants = (
            db.query(assistant.label("assistant"), func.count(Visit.id).label("views"),
                     func.count(func.distinct(_visitor_key())).label("visitors"))
            .filter(*filters).group_by(assistant).order_by(desc("views")).all()
        )
        pages = (
            db.query(Visit.page_domain, Visit.path, func.count(Visit.id).label("views"),
                     func.count(func.distinct(_visitor_key())).label("visitors"))
            .filter(*filters).group_by(Visit.page_domain, Visit.path).order_by(desc("views")).limit(25).all()
        )
        day = self._day(db, Visit.timestamp)
        daily = (
            db.query(day.label("day"), assistant.label("assistant"), func.count(Visit.id).label("views"))
            .filter(*filters).group_by(day, assistant).order_by(day).all()
        )

        ai_hosts = [v for v in AI_ASSISTANT_SOURCES if "." in v]
        lead_rows = (
            db.query(LeadSummary)
            .filter(*_in_range(LeadSummary.last_seen, since, until))
            .filter(or_(func.lower(LeadSummary.source).in_(list(AI_ASSISTANT_SOURCES)),
                        func.lower(LeadSummary.first_referrer_domain).in_(ai_hosts)))
            .order_by(LeadSummary.last_seen.desc()).limit(50).all()
        )
        return {
            "views": totals[0] or 0,
            "visitors": totals[1] or 0,
            "assistants": [{"assistant": r.assistant, "views": r.views, "visitors": r.visitors} for r in assistants],
            "pages": [{"domain": r.page_domain, "path": r.path, "views": r.views, "visitors": r.visitors} for r in pages],
            "daily": [{"day": str(r.day), "assistant": r.assistant, "views": r.views} for r in daily],
            "leads": [{
                "client_id": l.client_id, "name": l.name, "email": l.email, "captured_path": l.captured_path,
                "captured_at": _iso(l.captured_at),
                "assistant": ai_assistant(l.source) or ai_assistant(l.first_referrer_domain),
            } for l in lead_rows],
        }

    # ---------- Companies (IP enrichment) ----------

    @staticmethod
    def _company_ip():
        """An enrichment row that names an actual organisation: not an ISP, host, VPN or proxy."""
        return and_(
            IpEnrichment.status == "success",
            IpEnrichment.company_domain.isnot(None), IpEnrichment.company_domain != "",
            func.coalesce(IpEnrichment.company_type, "").notin_(["isp", "hosting"]),
            func.coalesce(IpEnrichment.is_datacenter, False) == False,  # noqa: E712
            func.coalesce(IpEnrichment.is_vpn, False) == False,  # noqa: E712
            func.coalesce(IpEnrichment.is_proxy, False) == False,  # noqa: E712
            func.coalesce(IpEnrichment.is_tor, False) == False,  # noqa: E712
        )

    def companies(self, db: Session, since=None, until=None, limit: int = 50) -> Dict[str, Any]:
        """Organisations behind human visits, from IP enrichment, with how much of the traffic that covers."""
        since, until = bounded(since, until)
        human = _in_range(Visit.timestamp, since, until) + [Visit.is_bot == False]  # noqa: E712
        company = self._company_ip()

        # Lookups made without an API key return only a name: no domain, type or network flags,
        # so they can't be told apart from ISPs and hosts and are counted separately
        detailed = and_(IpEnrichment.status == "success",
                        or_(IpEnrichment.company_domain.isnot(None), IpEnrichment.company_type.isnot(None)))
        cov = (
            db.query(
                func.count(func.distinct(Visit.session_id)),
                func.count(func.distinct(case((IpEnrichment.status == "success", Visit.session_id)))),
                func.count(func.distinct(case((detailed, Visit.session_id)))),
                func.count(func.distinct(case((company, Visit.session_id)))),
            )
            .outerjoin(IpEnrichment, IpEnrichment.ip == Visit.ip_address)
            .filter(*human).one()
        )
        rows = (
            db.query(
                IpEnrichment.company_domain.label("domain"),
                func.max(IpEnrichment.company_name).label("name"),
                func.max(IpEnrichment.company_type).label("type"),
                func.max(IpEnrichment.country).label("country"),
                func.count(Visit.id).label("views"),
                func.count(func.distinct(Visit.session_id)).label("sessions"),
                func.count(func.distinct(_visitor_key())).label("visitors"),
                func.max(Visit.timestamp).label("last_seen"),
            )
            .join(IpEnrichment, IpEnrichment.ip == Visit.ip_address)
            .filter(*human, company)
            .group_by(IpEnrichment.company_domain).order_by(desc("views")).limit(limit).all()
        )
        pages: Dict[str, list] = {}
        if rows:
            for p in (
                db.query(IpEnrichment.company_domain, Visit.page_domain, Visit.path, func.count(Visit.id).label("views"))
                .join(IpEnrichment, IpEnrichment.ip == Visit.ip_address)
                .filter(*human, company, IpEnrichment.company_domain.in_([r.domain for r in rows]))
                .group_by(IpEnrichment.company_domain, Visit.page_domain, Visit.path)
                .order_by(desc("views")).all()
            ):
                lst = pages.setdefault(p.company_domain, [])
                if len(lst) < 8:
                    lst.append({"domain": p.page_domain, "path": p.path, "views": p.views})
        return {
            "coverage": {
                "human_sessions": cov[0] or 0, "enriched_sessions": cov[1] or 0,
                "detailed_sessions": cov[2] or 0, "company_sessions": cov[3] or 0,
            },
            "companies": [{
                "domain": r.domain, "name": r.name, "type": r.type, "country": r.country, "views": r.views,
                "sessions": r.sessions, "visitors": r.visitors, "last_seen": _iso(r.last_seen), "pages": pages.get(r.domain, []),
            } for r in rows],
        }

    # ---------- Tracking health ----------

    _DOMAINS_PG = text(
        """
        WITH RECURSIVE d AS (
            SELECT min(page_domain) AS dom FROM visits
            UNION ALL
            SELECT (SELECT min(page_domain) FROM visits WHERE page_domain > d.dom) FROM d WHERE d.dom IS NOT NULL
        )
        SELECT dom AS domain,
               (SELECT max(timestamp) FROM visits v WHERE v.page_domain = d.dom) AS last_seen,
               (SELECT count(*) FROM visits v WHERE v.page_domain = d.dom AND v.timestamp >= :day_ago) AS views_24h,
               (SELECT count(*) FROM visits v WHERE v.page_domain = d.dom AND v.timestamp >= :week_ago) AS views_7d
        FROM d WHERE dom IS NOT NULL
        """
    )

    def tracking_health(self, db: Session, now: Optional[datetime] = None) -> Dict[str, Any]:
        """Last page view per tracked site and tracking ID, so a silent tracker stands out."""
        now = now or datetime.now(timezone.utc)
        day_ago, week_ago, month_ago = now - timedelta(days=1), now - timedelta(days=7), now - timedelta(days=30)
        if db.bind.dialect.name == "postgresql":
            # A skip scan over (page_domain, timestamp): one index probe per domain instead of a full scan
            domains = db.execute(self._DOMAINS_PG, {"day_ago": day_ago, "week_ago": week_ago}).mappings().all()
        else:
            domains = db.query(
                Visit.page_domain.label("domain"), func.max(Visit.timestamp).label("last_seen"),
                func.sum(case((Visit.timestamp >= day_ago, 1), else_=0)).label("views_24h"),
                func.sum(case((Visit.timestamp >= week_ago, 1), else_=0)).label("views_7d"),
            ).filter(Visit.page_domain.isnot(None)).group_by(Visit.page_domain).all()
            domains = [dict(r._mapping) for r in domains]

        ids: Dict[str, list] = {}
        for r in (
            db.query(Visit.page_domain, Visit.tracking_id, func.count(Visit.id).label("views"), func.max(Visit.timestamp).label("last_seen"))
            .filter(Visit.timestamp >= month_ago, Visit.page_domain.isnot(None))
            .group_by(Visit.page_domain, Visit.tracking_id).all()
        ):
            ids.setdefault(r.page_domain, []).append({
                "tracking_id": r.tracking_id, "views_30d": r.views, "last_seen": _iso(r.last_seen),
                "status": tracking_status(r.last_seen, now),
            })

        sites, hidden = [], 0
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        # Our own sites first, then most recently seen
        for d in sorted(domains, key=lambda d: (not is_internal_domain(d["domain"]), -(_aware(d["last_seen"]) or epoch).timestamp())):
            if is_junk_domain(d["domain"]):
                hidden += 1
                continue
            sites.append({
                "domain": d["domain"],
                "ours": is_internal_domain(d["domain"]),
                "last_seen": _iso(d["last_seen"]),
                "status": tracking_status(d["last_seen"], now),
                "views_24h": int(d["views_24h"] or 0),
                "views_7d": int(d["views_7d"] or 0),
                "tracking_ids": sorted(ids.get(d["domain"], []), key=lambda t: -t["views_30d"]),
            })
        return {"checked_at": now.isoformat(), "sites": sites, "hidden_domains": hidden}

    # ---------- Global search ----------

    _TOKEN = re.compile(r"^[A-Za-z0-9_.:-]{6,128}$")

    def search(self, db: Session, q: str, limit: int = 8) -> Dict[str, Any]:
        """Match a pasted email, name, client ID, session ID or URL to something the dashboard can open."""
        q = (q or "").strip()
        results: List[Dict[str, Any]] = []
        if len(q) < 2:
            return {"query": q, "results": results}

        def add(kind: str, id_: str, label: str, detail: Optional[str] = None, **extra):
            if not any(r["kind"] == kind and r["id"] == id_ for r in results):
                results.append({"kind": kind, "id": id_, "label": label, "detail": detail, **extra})

        def leads_matching(*conds):
            found = 0
            for l in db.query(LeadSummary).filter(or_(*conds)).order_by(LeadSummary.last_seen.desc()).limit(200):
                # The SQL match also hits form questions; keep leads whose own details match
                if not lead_matches(l, q):
                    continue
                add("journey", l.client_id, l.name or l.email or l.client_id,
                    " · ".join(x for x in [l.email if l.name else None, l.captured_path, _iso(l.last_seen)] if x))
                found += 1
                if found >= limit:
                    break

        if re.match(r"^https?://", q, re.I) or ("/" in q and "." in q.split("/")[0] and " " not in q):
            url = q if re.match(r"^https?://", q, re.I) else f"https://{q}"
            parsed = urlparse(url)
            params = {k: v[0] for k, v in parse_qs(parsed.query).items() if v}
            cid = params.get("cd_cid") or params.get("cid") or params.get("client_id")
            if cid:
                add("journey", cid, "Visitor from this link", cid)
            add("page", url, parsed.path or "/", parsed.netloc, domain=parsed.netloc, path=parsed.path or "/")
            return {"query": q, "results": results}

        if q.startswith("/") and " " not in q:
            add("page", q, q.split("?")[0], "Page views on any site", domain=None, path=q.split("?")[0])
            return {"query": q, "results": results}

        if "@" in q:
            p = like_pattern(q)
            leads_matching(LeadSummary.email.ilike(p, escape="\\"))
            for j in db.query(JourneySummary).filter(JourneySummary.email.ilike(p, escape="\\")).limit(limit):
                add("journey", j.client_id, j.name or j.email or j.client_id, j.email)
            return {"query": q, "results": results[:limit]}

        if self._TOKEN.match(q):
            session = db.get(VisitSession, q)
            if session:
                add("session", session.id, "Session", f"last active {_iso(session.last_visit)}")
            seen = (
                db.query(func.max(VisitSession.last_visit), func.count(VisitSession.id))
                .filter(VisitSession.client_id == q).one()
            )
            if seen[1]:
                add("journey", q, "Visitor journey", f"{seen[1]} sessions · last active {_iso(seen[0])}")
            if not results and len(q) >= 8:
                # A shortened ID, as the tables show them (the C collation lets these use the btree indexes)
                for s in db.query(VisitSession.id, VisitSession.last_visit).filter(VisitSession.id.like(f"{q}%")).limit(3):
                    add("session", s.id, "Session", f"last active {_iso(s.last_visit)}")
                for (cid,) in db.query(VisitSession.client_id).filter(VisitSession.client_id.like(f"{q}%")).distinct().limit(3):
                    add("journey", cid, "Visitor journey", cid)

        p = like_pattern(q)
        leads_matching(LeadSummary.name.ilike(p, escape="\\"), LeadSummary.email.ilike(p, escape="\\"),
                       LeadSummary.captured_data.ilike(p, escape="\\"))
        return {"query": q, "results": results[:limit]}
