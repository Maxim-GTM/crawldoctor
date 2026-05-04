"""Periodic IP enrichment background job."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.background.registry import registry
from app.config import settings

import structlog

logger = structlog.get_logger()


@registry.job("ip_enrichment", sweep_interval_minutes=settings.ip_enrichment_interval_minutes)
class IpEnrichmentJob:
    """Scheduled batch enrichment of visitor IPs.

    Sweep fires every ip_enrichment_interval_minutes; handle runs one batch
    via IpEnrichmentService so rate limiting and retry logic are preserved.
    """

    def sweep(self, db: Session, since: datetime) -> List[Dict[str, Any]]:
        if not settings.ip_enrichment_enabled:
            return []
        return [{"trigger": "scheduled"}]

    def handle(self, db: Session, payload: Dict[str, Any]) -> None:
        from app.services.ip_enrichment import IpEnrichmentService
        IpEnrichmentService().run_batch(db)
