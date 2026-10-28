"""Reconciliation job: recomputes leads whose lead_summaries row is missing or unclassified."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.background.registry import registry

import structlog

logger = structlog.get_logger()


@registry.job("reconcile_leads", sweep_interval_minutes=60)
class ReconcileLeads:
    """Hourly sweep that catches client_ids whose lead_summaries row is missing or has no lead_type.

    Missing rows: a recompute_journey job was lost (e.g. server restart) after the
    watermark already advanced past their events. No lead_type: leads written before
    recompute_journey classified them (everything after 2026-08-26); recomputing fills
    it in, 500 leads per sweep. Duplicate form fills: two workers recomputed the same
    client at once (before recompute_journey took a per-client lock). The sweep ignores
    `since` — it always does a full consistency check.
    """

    def sweep(self, db: Session, since: datetime) -> List[Dict[str, Any]]:
        rows = db.execute(text("""
            SELECT js.client_id
            FROM journey_summaries js
            LEFT JOIN lead_summaries ls ON ls.client_id = js.client_id
            WHERE js.has_captured_data = 1
              AND (ls.client_id IS NULL
                   OR ls.lead_type IS NULL
                   OR EXISTS (
                       SELECT 1 FROM journey_form_fills f
                       WHERE f.client_id = js.client_id AND f.visit_event_id IS NOT NULL
                       GROUP BY f.visit_event_id
                       HAVING count(*) > 1
                   ))
            LIMIT 500
        """)).fetchall()

        if rows:
            logger.info("reconcile_leads found journeys to recompute", count=len(rows))

        return [{"client_id": row[0]} for row in rows]

    def handle(self, db: Session, payload: Dict[str, Any]) -> None:
        from app.background.registry import registry as _registry
        handler = _registry.get_handler("recompute_journey")
        handler.handle(db, payload)
