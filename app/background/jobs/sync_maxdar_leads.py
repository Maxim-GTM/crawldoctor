"""Copy the demo and enterprise requests the tracker missed from maxdar.

The tracker loads through Google Tag Manager, which ad and privacy blockers stop: between
2026-10-12 and 2026-11-02 it recorded 68 of the 121 demo and enterprise requests, and on 2026-11-02
none of the four Bifrost demos. Their browsers sent nothing, not even a page view. maxdar (the GTM
team's Neon project) gets every submission of those forms, so this job reads them there through
maxdar_database_url and records the ones the tracker didn't:

- a submission the tracker has (a form fill with the same email within 30 minutes) is left alone;
- any other is stored as a form_submit with tracking_method "server", on the client of an existing
  lead with that email or on a client made from the email, and recompute_journey makes it a lead.
  Such leads have no visits, so no pages or source.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import urlparse

from sqlalchemy import create_engine, func, text
from sqlalchemy.orm import Session
import structlog

from app.background.jobs.recompute_journey import SAME_SUBMISSION_WINDOW, SERVER_TRACKING_METHOD, form_email
from app.background.registry import registry
from app.config import settings
from app.models.summary import LeadSummary
from app.models.visit import VisitEvent, fit_to_columns

logger = structlog.get_logger()

# maxdar category -> the page of its form, which decides the lead type (lead_classification).
FORM_PAGES = {
    "Bifrost Demos": "https://www.getmaxim.ai/book-a-demo",
    "Enterprise License Requests": "https://www.getmaxim.ai/enterprise",
}

# A submission maxdar got in the last two minutes waits for the next sweep: the tracker's own
# form_submit for it may still be on its way.
_SETTLE = timedelta(minutes=2)
# Each sweep reads this far back past its watermark, so those waiting rows are not skipped.
# Rows already copied are recognised by their message_id.
_OVERLAP = timedelta(minutes=15)

_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "crawldoctor.agitracker.io")

_engine = None


def _maxdar():
    global _engine
    if _engine is None:
        _engine = create_engine(
            settings.maxdar_database_url, pool_pre_ping=True, pool_size=1, max_overflow=0,
            connect_args={"connect_timeout": 10},
        )
    return _engine


def fetch_submissions(since: datetime, until: datetime) -> List[Mapping[str, Any]]:
    """maxdar's demo and enterprise requests received in (since, until], oldest first."""
    with _maxdar().connect() as conn:
        return conn.execute(text("""
            SELECT id, category, booked_email, first_name, last_name, company_size,
                   company_location, created_at
            FROM events
            WHERE created_at > :since AND created_at <= :until
              AND category = ANY(:categories)
              AND is_junk IS NOT TRUE
            ORDER BY created_at
        """), {"since": since, "until": until, "categories": list(FORM_PAGES)}).mappings().all()


def _utc(ts: datetime) -> datetime:
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts


def _tracked(db: Session, email: str, at: datetime) -> bool:
    """True if the tracker recorded a form fill with this email around this time."""
    rows = db.query(VisitEvent.event_data).filter(
        VisitEvent.event_type == "form_submit",
        VisitEvent.timestamp >= at - SAME_SUBMISSION_WINDOW,
        VisitEvent.timestamp <= at + SAME_SUBMISSION_WINDOW,
    ).all()
    for (data,) in rows:
        data = data if isinstance(data, dict) else {}
        if data.get("tracking_method") == SERVER_TRACKING_METHOD:
            continue
        if form_email(data.get("form_values") or data.get("values")) == email:
            return True
    return False


def record_submission(db: Session, row: Mapping[str, Any]) -> Optional[str]:
    """Store one maxdar submission as a form fill; return its client_id.

    None when it was copied before, the tracker has it, or it has no usable email.
    """
    message_id = str(uuid.uuid5(_NAMESPACE, f"maxdar:{row['id']}"))
    if db.query(VisitEvent.id).filter(VisitEvent.message_id == message_id).first():
        return None

    values = {
        "FirstName": row.get("first_name"),
        "LastName": row.get("last_name"),
        "Email": (row.get("booked_email") or "").strip(),
        "CompanySize": row.get("company_size"),
        "Location": row.get("company_location"),
    }
    values = {k: str(v).strip() for k, v in values.items() if v is not None and str(v).strip()}
    email = form_email(values)
    submitted_at = _utc(row["created_at"])
    if not email or _tracked(db, email, submitted_at):
        return None

    client_id = (
        db.query(LeadSummary.client_id)
        .filter(func.lower(LeadSummary.email) == email)
        .order_by(LeadSummary.last_seen.desc())
        .limit(1)
        .scalar()
    ) or f"lead-{uuid.uuid5(_NAMESPACE, f'email:{email}')}"

    page = urlparse(FORM_PAGES[row["category"]])
    db.add(VisitEvent(**fit_to_columns(VisitEvent.__table__, {
        "client_id": client_id,
        "timestamp": submitted_at,
        "event_type": "form_submit",
        "page_url": page.geturl(),
        "path": page.path,
        "page_domain": page.netloc,
        "message_id": message_id,
        "event_data": {
            "id": None,
            "action": None,
            "filled_fields": len(values),
            "form_values": values,
            "tracking_method": SERVER_TRACKING_METHOD,
            "origin": f"maxdar:events:{row['id']}",
        },
    })))
    db.flush()
    return client_id


@registry.job("sync_maxdar_leads", sweep_interval_minutes=5)
class SyncMaxdarLeads:
    """Sweep: copy maxdar's new submissions the tracker missed. Handle: recompute that lead.

    The first sweep reads back summary_backfill_days, so the leads missed before it ran appear too.
    """

    def sweep(self, db: Session, since: datetime) -> List[Dict[str, Any]]:
        if not settings.maxdar_database_url:
            return []
        rows = fetch_submissions(_utc(since) - _OVERLAP, datetime.now(timezone.utc) - _SETTLE)
        clients = []
        for row in rows:
            client_id = record_submission(db, row)
            if client_id and client_id not in clients:
                clients.append(client_id)
        db.commit()
        if clients:
            logger.info("Copied leads the tracker missed from maxdar", read=len(rows), leads=len(clients))
        return [{"client_id": client_id} for client_id in clients]

    def handle(self, db: Session, payload: Dict[str, Any]) -> None:
        registry.get_handler("recompute_journey").handle(db, payload)
