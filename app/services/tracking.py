"""Simplified tracking service for logging ALL visits with automatic categorization."""
import hashlib
import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse, parse_qs

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import object_session
import structlog

from app.models.visit import Visit, VisitSession, VisitEvent
from app.services.crawler_detection import CrawlerDetectionService, CrawlerDetectionResult
from app.services.analytics import is_real_form_submit
from app.services.event_batcher import event_batcher
from app.background.runner import job_runner
from app.services.geo import GeoLocationService
from app.utils.domains import is_internal_domain, classify_domain
from app.config import settings

logger = structlog.get_logger()


class TrackingService:
    """Simplified service for tracking ALL visits with automatic categorization."""

    def __init__(self):
        self.crawler_detector = CrawlerDetectionService()
        self.geo_service = GeoLocationService()

    # ------------------------------------------------------------------
    # Session identity helpers
    # ------------------------------------------------------------------

    def _generate_session_id(
        self,
        ip_address: str,
        user_agent: str,
        client_id: Optional[str] = None,
        journey_seq: int = 0,
    ) -> str:
        if client_id:
            session_data = f"cid:{client_id}:journey:{journey_seq}"
        else:
            session_data = f"ipua:{ip_address}:{user_agent}:journey:{journey_seq}"
        return hashlib.sha256(session_data.encode()).hexdigest()[:32]

    def _is_external_entry(
        self,
        referrer: Optional[str],
        referrer_domain: Optional[str],
        page_domain: Optional[str],
        event_type: Optional[str] = None,
        source: Optional[str] = None,
        medium: Optional[str] = None,
        campaign: Optional[str] = None,
    ) -> bool:
        if event_type in ("heartbeat", "visibility", "scroll"):
            return False

        if referrer_domain:
            if is_internal_domain(referrer_domain):
                return False
            return True

        if source:
            src_lower = source.lower()
            if is_internal_domain(src_lower):
                return False
            _EXTERNAL_SOURCES = {
                "google", "bing", "yahoo", "duckduckgo",
                "linkedin", "facebook", "twitter", "instagram",
                "reddit", "youtube", "tiktok", "github",
            }
            if src_lower in _EXTERNAL_SOURCES:
                return True
            return True

        if medium or campaign:
            return True

        return True

    _SESSION_RACE_WINDOW = timedelta(seconds=30)

    async def _resolve_existing_session(
        self,
        db: AsyncSession,
        ip_address: str,
        user_agent: str,
        client_id: Optional[str] = None,
    ) -> Optional[VisitSession]:
        try:
            if client_id:
                result = await db.execute(
                    select(VisitSession)
                    .where(VisitSession.client_id == client_id)
                    .order_by(VisitSession.last_visit.desc())
                    .limit(1)
                )
                session = result.scalar_one_or_none()
                if session:
                    return session

            result = await db.execute(
                select(VisitSession)
                .where(
                    VisitSession.ip_address == ip_address,
                    VisitSession.user_agent == user_agent[:500],
                )
                .order_by(VisitSession.last_visit.desc())
                .limit(1)
            )
            return result.scalar_one_or_none()
        except Exception:
            return None

    async def _dedup_racing_session(
        self,
        db: AsyncSession,
        session: "VisitSession",
        client_id: Optional[str],
        ip_address: str,
        user_agent: str,
    ) -> "VisitSession":
        try:
            cutoff = datetime.now(timezone.utc) - self._SESSION_RACE_WINDOW
            if client_id:
                result = await db.execute(
                    select(VisitSession)
                    .where(
                        VisitSession.client_id == client_id,
                        VisitSession.id != session.id,
                        VisitSession.first_visit >= cutoff,
                    )
                    .order_by(VisitSession.first_visit.asc())
                    .limit(1)
                )
            else:
                result = await db.execute(
                    select(VisitSession)
                    .where(
                        VisitSession.ip_address == ip_address,
                        VisitSession.user_agent == user_agent[:500],
                        VisitSession.id != session.id,
                        VisitSession.first_visit >= cutoff,
                    )
                    .order_by(VisitSession.first_visit.asc())
                    .limit(1)
                )
            older = result.scalar_one_or_none()
            if older:
                logger.info(
                    "Merging racing session",
                    new_session=session.id[:12],
                    into_session=older.id[:12],
                    client_id=client_id[:12] if client_id else None,
                )
                try:
                    db.expunge(session)
                except Exception:
                    pass
                return older
        except Exception:
            pass
        return session

    async def _next_journey_seq(
        self,
        db: AsyncSession,
        ip_address: str,
        user_agent: str,
        client_id: Optional[str] = None,
    ) -> int:
        try:
            if client_id:
                result = await db.execute(
                    select(func.count(VisitSession.id))
                    .where(VisitSession.client_id == client_id)
                )
            else:
                result = await db.execute(
                    select(func.count(VisitSession.id))
                    .where(
                        VisitSession.ip_address == ip_address,
                        VisitSession.user_agent == user_agent[:500],
                    )
                )
            return result.scalar() or 0
        except Exception:
            return 0

    def _extract_page_info(self, url: str) -> Dict[str, Any]:
        if not url:
            return {}
        try:
            parsed = urlparse(url)
            return {
                "domain": parsed.netloc,
                "protocol": parsed.scheme,
                "port": parsed.port,
                "path": parsed.path,
                "query_params": dict(parse_qs(parsed.query))
            }
        except Exception:
            return {}

    def _extract_utm(self, page_info: Dict[str, Any], referrer: Optional[str]) -> Dict[str, Optional[str]]:
        utm = {"source": None, "medium": None, "campaign": None}
        try:
            q = page_info.get("query_params") or {}
            if isinstance(q, dict):
                utm["source"] = (q.get("utm_source") or q.get("source") or q.get("ref") or [None])[0]
                utm["medium"] = (q.get("utm_medium") or [None])[0]
                utm["campaign"] = (q.get("utm_campaign") or q.get("campaign") or [None])[0]
        except Exception:
            pass
        if not utm["source"] and referrer:
            try:
                r = urlparse(referrer)
                utm["source"] = r.netloc
            except Exception:
                pass
        return utm

    def _categorize_visitor(self, user_agent: str) -> Dict[str, Any]:
        detection_result = self.crawler_detector.detect_crawler(user_agent)

        category = "unknown"
        if "gpt" in user_agent.lower() or "openai" in user_agent.lower():
            category = "chatgpt"
        elif "claude" in user_agent.lower() or "anthropic" in user_agent.lower():
            category = "claude"
        elif "perplexity" in user_agent.lower():
            category = "perplexity"
        elif "google" in user_agent.lower() and "ai" in user_agent.lower():
            category = "google_ai"
        elif "bot" in user_agent.lower():
            category = "bot"
        elif "mobile" in user_agent.lower():
            category = "mobile_human"
        elif "mozilla" in user_agent.lower() or "chrome" in user_agent.lower() or "safari" in user_agent.lower():
            category = "desktop_human"
        else:
            category = "other"

        return {
            "category": category,
            "is_crawler": detection_result.is_crawler,
            "crawler_name": detection_result.crawler_name,
            "confidence": detection_result.confidence_score,
            "detection_method": detection_result.detection_method
        }

    async def track_visit(
        self,
        db: AsyncSession,
        ip_address: str,
        user_agent: str,
        page_url: Optional[str] = None,
        referrer: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        tracking_id: Optional[str] = None,
        custom_data: Optional[Dict[str, Any]] = None,
        client_id: Optional[str] = None,
        client_side_data: Optional[Dict[str, Any]] = None,
    ) -> Visit:
        """Track ANY visit with automatic categorization."""
        page_info = self._extract_page_info(page_url or "")

        referrer_domain = None
        if referrer:
            try:
                referrer_domain = urlparse(referrer).netloc
            except Exception:
                pass

        utm_info = self._extract_utm(page_info, referrer)

        existing_session = await self._resolve_existing_session(db, ip_address, user_agent, client_id)

        if existing_session and not self._is_external_entry(
            referrer, referrer_domain, page_info.get("domain"),
            event_type="page_view", source=utm_info.get("source"),
            medium=utm_info.get("medium"), campaign=utm_info.get("campaign"),
        ):
            session_id = existing_session.id
            session = existing_session
        else:
            seq = await self._next_journey_seq(db, ip_address, user_agent, client_id)
            session_id = self._generate_session_id(ip_address, user_agent, client_id, seq)
            result = await db.execute(select(VisitSession).where(VisitSession.id == session_id))
            session = result.scalar_one_or_none()

        is_new_session = session is None
        if not session:
            session = VisitSession(
                id=session_id,
                ip_address=ip_address,
                user_agent=user_agent[:500],
                client_id=client_id,
                first_visit=datetime.now(timezone.utc),
                last_visit=datetime.now(timezone.utc),
                visit_count=0,
                entry_referrer=referrer[:2000] if referrer else None,
                entry_referrer_domain=referrer_domain,
                is_external_entry=is_new_session,
            )
            session = await self._dedup_racing_session(db, session, client_id, ip_address, user_agent)
            session_id = session.id
            is_new_session = object_session(session) is None
            if is_new_session and client_side_data:
                session.client_side_timezone = client_side_data.get('timezone')
                session.client_side_language = client_side_data.get('language')
                session.client_side_screen_resolution = client_side_data.get('screen_resolution')
                session.client_side_viewport_size = client_side_data.get('viewport_size')
                session.client_side_device_memory = client_side_data.get('device_memory')
                session.client_side_connection_type = client_side_data.get('connection_type')
        else:
            is_new_session = False
            if client_id and not session.client_id:
                session.client_id = client_id
            if client_side_data:
                if not session.client_side_timezone:
                    session.client_side_timezone = client_side_data.get('timezone')
                if not session.client_side_language:
                    session.client_side_language = client_side_data.get('language')
                if not session.client_side_screen_resolution:
                    session.client_side_screen_resolution = client_side_data.get('screen_resolution')
                if not session.client_side_viewport_size:
                    session.client_side_viewport_size = client_side_data.get('viewport_size')
                if not session.client_side_device_memory:
                    session.client_side_device_memory = client_side_data.get('device_memory')
                if not session.client_side_connection_type:
                    session.client_side_connection_type = client_side_data.get('connection_type')

        session.last_visit = datetime.now(timezone.utc)

        visitor_info = self._categorize_visitor(user_agent)
        geo_info = await self.geo_service.get_location_info(ip_address, category="bot" if visitor_info.get("is_crawler") else "human")

        try:
            if geo_info:
                if not session.country:
                    session.country = geo_info.get("country_code")
                if not session.country_name:
                    session.country_name = geo_info.get("country_name")
                if not session.city:
                    session.city = geo_info.get("city")
                if session.latitude is None:
                    session.latitude = geo_info.get("latitude")
                if session.longitude is None:
                    session.longitude = geo_info.get("longitude")
                if not session.timezone:
                    session.timezone = geo_info.get("timezone")
                if not session.isp:
                    session.isp = geo_info.get("isp")
                if not session.organization:
                    session.organization = geo_info.get("organization")
                if not session.asn:
                    session.asn = geo_info.get("asn")
        except Exception:
            pass

        existing_visit: Optional[Visit] = None
        try:
            if page_url:
                cutoff_ts = datetime.now(timezone.utc) - timedelta(seconds=30)
                result = await db.execute(
                    select(Visit)
                    .where(
                        Visit.session_id == session_id,
                        Visit.page_url == page_url,
                        Visit.timestamp >= cutoff_ts,
                    )
                    .order_by(Visit.timestamp.desc())
                    .limit(1)
                )
                existing_visit = result.scalar_one_or_none()
        except Exception:
            existing_visit = None

        if existing_visit:
            if not is_new_session:
                db.add(session)
            updated = False
            if headers:
                try:
                    merged = existing_visit.request_headers or {}
                    merged.update({k: v for k, v in (headers or {}).items() if k not in merged})
                    existing_visit.request_headers = merged
                    updated = True
                except Exception:
                    pass
            if custom_data:
                try:
                    rh = existing_visit.request_headers or {}
                    custom = rh.get("custom_data", {})
                    if isinstance(custom, dict):
                        custom.update(custom_data)
                    else:
                        custom = custom_data
                    rh["custom_data"] = custom
                    existing_visit.request_headers = rh
                    updated = True
                except Exception:
                    pass
            if tracking_id and not existing_visit.tracking_id:
                existing_visit.tracking_id = tracking_id
                updated = True
            try:
                if updated:
                    db.add(existing_visit)
                await db.commit()
                if updated:
                    await db.refresh(existing_visit)
            except Exception:
                await db.rollback()
            return existing_visit

        db.add(session)

        visit_country = geo_info.get("country_code") if geo_info else None
        visit_city = geo_info.get("city") if geo_info else None

        if not visit_country and session:
            visit_country = session.country
            visit_city = session.city

        visit = Visit(
            session_id=session_id,
            client_id=client_id,
            ip_address=ip_address,
            user_agent=user_agent[:1000],
            page_url=page_url[:2000] if page_url else None,
            referrer=referrer[:2000] if referrer else None,
            page_domain=page_info.get("domain"),
            crawler_type=visitor_info["crawler_name"],
            crawler_confidence=visitor_info["confidence"],
            is_bot=visitor_info["is_crawler"],
            request_headers=headers if headers else {},
            country=visit_country,
            city=visit_city,
            tracking_id=tracking_id,
            source=utm_info.get("source"),
            medium=utm_info.get("medium"),
            campaign=utm_info.get("campaign"),
            protocol=page_info.get("protocol"),
            port=page_info.get("port"),
            path=page_info.get("path"),
            query_params=page_info.get("query_params", {}),
            client_side_timezone=client_side_data.get('timezone') if client_side_data else None,
            client_side_language=client_side_data.get('language') if client_side_data else None,
            client_side_screen_resolution=client_side_data.get('screen_resolution') if client_side_data else None,
            client_side_viewport_size=client_side_data.get('viewport_size') if client_side_data else None,
            client_side_device_memory=client_side_data.get('device_memory') if client_side_data else None,
            client_side_connection_type=client_side_data.get('connection_type') if client_side_data else None
        )

        if custom_data:
            visit.request_headers.update({"custom_data": custom_data})

        db.add(visit)
        try:
            session.visit_count = (session.visit_count or 0) + 1
            db.add(session)
        except Exception:
            pass
        await db.commit()
        await db.refresh(visit)

        logger.info(
            "Visit tracked",
            visit_id=visit.id,
            category=visitor_info["category"],
            user_agent=user_agent[:200],
            ip_address=ip_address,
            page_url=page_url,
            is_crawler=visitor_info["is_crawler"],
            crawler_name=visitor_info["crawler_name"],
            confidence=visitor_info["confidence"]
        )

        return visit

    async def track_event(
        self,
        db: AsyncSession,
        ip_address: str,
        user_agent: str,
        event_type: str,
        page_url: Optional[str] = None,
        referrer: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        visit_id: Optional[int] = None,
        tracking_id: Optional[str] = None,
        client_id: Optional[str] = None,
        client_side_data: Optional[Dict[str, Any]] = None,
        message_id: Optional[str] = None,
        occurred_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Track fine-grained events like scroll, click, navigation."""
        if event_type == 'form_submit' and data:
            data_str = str(data)
            if 'timingsV2' in data_str or 'memory.totalJSHeapSize' in data_str or 'eventType' in data_str:
                logger.warning("Dropped noisy form_submit event", ip=ip_address, data_keys=list(data.keys()))
                return {"event_id": None, "queued": False, "status": "dropped_noise"}

            for k, v in data.items():
                k_str = str(k).lower()
                if k_str.startswith('payload.') or k_str == 'action' and str(v) == 'page_hit':
                    return {"event_id": None, "queued": False, "status": "dropped_noise"}

        page_info = self._extract_page_info(page_url or "")
        page_domain = page_info.get("domain")
        referrer_domain = None
        if referrer:
            try:
                referrer_domain = urlparse(referrer).netloc
            except Exception:
                referrer_domain = None

        visitor_info = self._categorize_visitor(user_agent)
        geo_info = await self.geo_service.get_location_info(ip_address, category="bot" if visitor_info.get("is_crawler") else "human")
        utm_info = self._extract_utm(page_info, referrer)

        existing_session = await self._resolve_existing_session(db, ip_address, user_agent, client_id)
        is_external = self._is_external_entry(
            referrer, referrer_domain, page_domain,
            event_type=event_type, source=utm_info.get("source"),
            medium=utm_info.get("medium"), campaign=utm_info.get("campaign"),
        )

        logger.info(
            "Session resolution",
            event_type=event_type,
            referrer_domain=referrer_domain,
            page_domain=page_domain,
            source=utm_info.get("source"),
            has_existing_session=existing_session is not None,
            existing_session_id=existing_session.id[:12] if existing_session else None,
            is_external=is_external,
            client_id=client_id[:12] if client_id else None,
        )

        if existing_session and not is_external:
            session_id = existing_session.id
        else:
            seq = await self._next_journey_seq(db, ip_address, user_agent, client_id)
            session_id = self._generate_session_id(ip_address, user_agent, client_id, seq)
            candidate = VisitSession(
                id=session_id, ip_address=ip_address,
                user_agent=user_agent[:500], client_id=client_id,
                first_visit=datetime.now(timezone.utc),
                last_visit=datetime.now(timezone.utc),
            )
            merged = await self._dedup_racing_session(db, candidate, client_id, ip_address, user_agent)
            if merged is not candidate:
                session_id = merged.id

        effective_session_id = session_id

        linked_visit: Optional[Visit] = None
        if visit_id:
            result = await db.execute(select(Visit).where(Visit.id == visit_id))
            linked_visit = result.scalar_one_or_none()
        if not linked_visit and page_url:
            try:
                cutoff = datetime.now(timezone.utc) - timedelta(seconds=90)
                result = await db.execute(
                    select(Visit)
                    .where(
                        Visit.page_url == page_url,
                        Visit.ip_address == ip_address,
                        Visit.timestamp >= cutoff,
                    )
                    .order_by(Visit.timestamp.desc())
                    .limit(1)
                )
                candidate = result.scalar_one_or_none()
                if candidate:
                    linked_visit = candidate
            except Exception:
                linked_visit = None
            if not linked_visit:
                try:
                    fallback_cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
                    stmt = select(Visit).where(
                        Visit.page_url == page_url,
                        Visit.timestamp >= fallback_cutoff,
                    )
                    if client_id:
                        stmt = stmt.where(Visit.client_id == client_id)
                    else:
                        stmt = stmt.where(
                            Visit.ip_address == ip_address,
                            Visit.user_agent == user_agent[:1000],
                        )
                    result = await db.execute(stmt.order_by(Visit.timestamp.desc()).limit(1))
                    linked_visit = result.scalar_one_or_none()
                except Exception:
                    linked_visit = None

        result = await db.execute(select(VisitSession).where(VisitSession.id == effective_session_id))
        session_row = result.scalar_one_or_none()
        if not session_row:
            existing_location = None
            try:
                result = await db.execute(
                    select(VisitSession)
                    .where(
                        VisitSession.ip_address == ip_address,
                        VisitSession.last_visit >= datetime.now(timezone.utc) - timedelta(hours=24),
                        VisitSession.country.isnot(None),
                        VisitSession.country != "XX",
                    )
                    .order_by(VisitSession.last_visit.desc())
                    .limit(1)
                )
                good_session = result.scalar_one_or_none()
                if good_session:
                    existing_location = {
                        "country": good_session.country,
                        "city": good_session.city,
                        "country_name": good_session.country_name,
                    }

                if not existing_location:
                    result = await db.execute(
                        select(Visit)
                        .where(
                            Visit.ip_address == ip_address,
                            Visit.timestamp >= datetime.now(timezone.utc) - timedelta(hours=24),
                            Visit.country.isnot(None),
                            Visit.country != "XX",
                        )
                        .order_by(Visit.timestamp.desc())
                        .limit(1)
                    )
                    good_visit = result.scalar_one_or_none()
                    if good_visit:
                        existing_location = {
                            "country": good_visit.country,
                            "city": good_visit.city,
                        }
            except Exception:
                pass

            session_row = VisitSession(
                id=effective_session_id,
                ip_address=ip_address,
                user_agent=user_agent[:500],
                client_id=client_id,
                first_visit=datetime.now(timezone.utc),
                last_visit=datetime.now(timezone.utc),
                visit_count=0,
                country=existing_location.get("country") if existing_location else None,
                city=existing_location.get("city") if existing_location else None,
                country_name=existing_location.get("country_name") if existing_location else None,
                entry_referrer=referrer[:2000] if referrer else None,
                entry_referrer_domain=referrer_domain,
                is_external_entry=True,
            )
            db.add(session_row)
            try:
                await db.flush()
            except IntegrityError:
                # Another concurrent worker inserted the same session — re-fetch it
                await db.rollback()
                result = await db.execute(
                    select(VisitSession).where(VisitSession.id == effective_session_id)
                )
                session_row = result.scalar_one_or_none()

        if not linked_visit and page_url:
            try:
                base_session_id = effective_session_id

                visit_country = None
                visit_city = None

                try:
                    result = await db.execute(
                        select(Visit)
                        .where(
                            Visit.ip_address == ip_address,
                            Visit.timestamp >= datetime.now(timezone.utc) - timedelta(hours=24),
                            Visit.country.isnot(None),
                            Visit.country != "XX",
                        )
                        .order_by(Visit.timestamp.desc())
                        .limit(1)
                    )
                    good_visit = result.scalar_one_or_none()
                    if good_visit:
                        visit_country = good_visit.country
                        visit_city = good_visit.city

                    if not visit_country:
                        result = await db.execute(
                            select(VisitSession)
                            .where(
                                VisitSession.ip_address == ip_address,
                                VisitSession.last_visit >= datetime.now(timezone.utc) - timedelta(hours=24),
                                VisitSession.country.isnot(None),
                                VisitSession.country != "XX",
                            )
                            .order_by(VisitSession.last_visit.desc())
                            .limit(1)
                        )
                        good_session = result.scalar_one_or_none()
                        if good_session:
                            visit_country = good_session.country
                            visit_city = good_session.city
                except Exception:
                    pass

                if not visit_country and geo_info:
                    if geo_info.get("country_code") and geo_info.get("country_code") != "XX":
                        visit_country = geo_info.get("country_code")
                        visit_city = geo_info.get("city")

                result = await db.execute(select(VisitSession).where(VisitSession.id == base_session_id))
                temp_session = result.scalar_one_or_none()
                if not visit_country and temp_session:
                    visit_country = temp_session.country
                    visit_city = temp_session.city

                new_visit = Visit(
                    session_id=base_session_id,
                    client_id=client_id,
                    ip_address=ip_address,
                    user_agent=user_agent[:1000],
                    page_url=page_url[:2000],
                    referrer=referrer[:2000] if referrer else None,
                    page_domain=page_info.get("domain"),
                    crawler_type=visitor_info["crawler_name"],
                    crawler_confidence=visitor_info["confidence"],
                    is_bot=visitor_info["is_crawler"],
                    request_headers={},
                    country=visit_country,
                    city=visit_city,
                    tracking_id=tracking_id,
                    source=utm_info.get("source"),
                    medium=utm_info.get("medium"),
                    campaign=utm_info.get("campaign"),
                    protocol=page_info.get("protocol"),
                    port=page_info.get("port"),
                    path=page_info.get("path"),
                    query_params=page_info.get("query_params", {})
                )
                db.add(new_visit)
                try:
                    session_row.visit_count = (session_row.visit_count or 0) + 1
                    db.add(session_row)
                except Exception:
                    pass
                await db.commit()
                await db.refresh(new_visit)
                linked_visit = new_visit
            except Exception:
                await db.rollback()

        if linked_visit:
            effective_session_id = linked_visit.session_id
            if client_id and linked_visit.session_id != session_id:
                target_session_id = session_id
                if linked_visit.session_id != target_session_id:
                    result = await db.execute(select(VisitSession).where(VisitSession.id == target_session_id))
                    target_session = result.scalar_one_or_none()
                    if not target_session:
                        target_session = VisitSession(
                            id=target_session_id,
                            ip_address=ip_address,
                            user_agent=user_agent[:500],
                            client_id=client_id,
                            first_visit=datetime.now(timezone.utc),
                            last_visit=datetime.now(timezone.utc),
                            visit_count=0
                        )
                        db.add(target_session)
                    linked_visit.session_id = target_session_id
                    effective_session_id = target_session_id
                    try:
                        db.add(linked_visit)
                        await db.commit()
                        await db.refresh(linked_visit)
                    except Exception:
                        await db.rollback()

        if effective_session_id != session_id:
            result = await db.execute(select(VisitSession).where(VisitSession.id == effective_session_id))
            session_row = result.scalar_one_or_none()
            if not session_row:
                session_row = VisitSession(
                    id=effective_session_id,
                    ip_address=ip_address,
                    user_agent=user_agent[:500],
                    client_id=client_id,
                    first_visit=datetime.now(timezone.utc),
                    last_visit=datetime.now(timezone.utc),
                    visit_count=0
                )
                db.add(session_row)

        session_row.last_visit = datetime.now(timezone.utc)
        db.add(session_row)

        try:
            needs_location_update = (
                not session_row.country or
                session_row.country == "XX" or
                not session_row.city or
                session_row.city == "Unknown"
            )

            if needs_location_update:
                inherited_location = None

                try:
                    result = await db.execute(
                        select(VisitSession)
                        .where(
                            VisitSession.ip_address == ip_address,
                            VisitSession.last_visit >= datetime.now(timezone.utc) - timedelta(hours=24),
                            VisitSession.id != session_row.id
                        )
                    )
                    recent_sessions = result.scalars().all()

                    for existing_sess in recent_sessions:
                        if existing_sess.country and existing_sess.country != "XX":
                            inherited_location = {
                                "country": existing_sess.country,
                                "city": existing_sess.city,
                                "country_name": existing_sess.country_name
                            }
                            break

                    if not inherited_location:
                        result = await db.execute(
                            select(Visit)
                            .where(
                                Visit.ip_address == ip_address,
                                Visit.timestamp >= datetime.now(timezone.utc) - timedelta(hours=24)
                            )
                        )
                        recent_visits = result.scalars().all()

                        for existing_visit in recent_visits:
                            if existing_visit.country and existing_visit.country != "XX":
                                inherited_location = {
                                    "country": existing_visit.country,
                                    "city": existing_visit.city
                                }
                                break
                except Exception:
                    pass

                if inherited_location:
                    if not session_row.country or session_row.country == "XX":
                        session_row.country = inherited_location["country"]
                    if not session_row.city or session_row.city == "Unknown":
                        session_row.city = inherited_location["city"]
                    if not session_row.country_name and inherited_location.get("country_name"):
                        session_row.country_name = inherited_location["country_name"]
                elif geo_info:
                    if geo_info.get("country_code") and geo_info.get("country_code") != "XX":
                        if not session_row.country or session_row.country == "XX":
                            session_row.country = geo_info.get("country_code")
                        if not session_row.city or session_row.city == "Unknown":
                            session_row.city = geo_info.get("city")
                        if not session_row.country_name:
                            session_row.country_name = geo_info.get("country_name")
                    elif not session_row.country:
                        session_row.country = geo_info.get("country_code")
                        session_row.city = geo_info.get("city")
                        session_row.country_name = geo_info.get("country_name")

                if geo_info:
                    if session_row.latitude is None:
                        session_row.latitude = geo_info.get("latitude")
                    if session_row.longitude is None:
                        session_row.longitude = geo_info.get("longitude")
                    if not session_row.timezone:
                        session_row.timezone = geo_info.get("timezone")
                    if not session_row.isp:
                        session_row.isp = geo_info.get("isp")
                    if not session_row.organization:
                        session_row.organization = geo_info.get("organization")
                    if not session_row.asn:
                        session_row.asn = geo_info.get("asn")

        except Exception:
            pass

        if client_side_data and session_row:
            try:
                if not session_row.client_side_timezone and client_side_data.get('timezone'):
                    session_row.client_side_timezone = client_side_data.get('timezone')
                if not session_row.client_side_language and client_side_data.get('language'):
                    session_row.client_side_language = client_side_data.get('language')
                if not session_row.client_side_screen_resolution and client_side_data.get('screen_resolution'):
                    session_row.client_side_screen_resolution = client_side_data.get('screen_resolution')
                if not session_row.client_side_viewport_size and client_side_data.get('viewport_size'):
                    session_row.client_side_viewport_size = client_side_data.get('viewport_size')
                if not session_row.client_side_device_memory and client_side_data.get('device_memory'):
                    session_row.client_side_device_memory = client_side_data.get('device_memory')
                if not session_row.client_side_connection_type and client_side_data.get('connection_type'):
                    session_row.client_side_connection_type = client_side_data.get('connection_type')
                logger.info("Session client-side data backfilled", session_id=session_row.id[:20] if session_row.id else None)
            except Exception as e:
                logger.error("Failed to backfill session client-side data", error=str(e))

        if not linked_visit:
            try:
                merge_cutoff = datetime.now(timezone.utc) - timedelta(seconds=180)
                result = await db.execute(
                    select(Visit)
                    .where(
                        Visit.ip_address == ip_address,
                        Visit.timestamp >= merge_cutoff,
                        Visit.session_id != effective_session_id,
                    )
                )
                recent_visits = result.scalars().all()
                changed = False
                for rv in recent_visits:
                    rv.session_id = effective_session_id
                    db.add(rv)
                    changed = True
                if changed:
                    await db.commit()
            except Exception:
                await db.rollback()

        event_country = None
        event_city = None

        if linked_visit and linked_visit.country and linked_visit.country != "XX":
            event_country = linked_visit.country
            event_city = linked_visit.city
        elif session_row and session_row.country and session_row.country != "XX":
            event_country = session_row.country
            event_city = session_row.city

        if not event_country:
            try:
                result = await db.execute(
                    select(VisitSession)
                    .where(
                        VisitSession.ip_address == ip_address,
                        VisitSession.last_visit >= datetime.now(timezone.utc) - timedelta(hours=24)
                    )
                )
                recent_sessions = result.scalars().all()

                for existing_sess in recent_sessions:
                    if existing_sess.country and existing_sess.country != "XX":
                        event_country = existing_sess.country
                        event_city = existing_sess.city
                        break

                if not event_country:
                    result = await db.execute(
                        select(Visit)
                        .where(
                            Visit.ip_address == ip_address,
                            Visit.timestamp >= datetime.now(timezone.utc) - timedelta(hours=24)
                        )
                    )
                    recent_visits = result.scalars().all()

                    for existing_visit in recent_visits:
                        if existing_visit.country and existing_visit.country != "XX":
                            event_country = existing_visit.country
                            event_city = existing_visit.city
                            break
            except Exception:
                pass

        if not event_country and geo_info:
            if geo_info.get("country_code") and geo_info.get("country_code") != "XX":
                event_country = geo_info.get("country_code")
                event_city = geo_info.get("city")
            elif session_row and session_row.country:
                event_country = session_row.country
                event_city = session_row.city

        if not event_country and geo_info:
            event_country = geo_info.get("country_code")
            event_city = geo_info.get("city")

        enriched_data = {
            **(data or {}),
            "tracking_id": tracking_id,
            "source": utm_info.get("source"),
            "medium": utm_info.get("medium"),
            "campaign": utm_info.get("campaign"),
            "crawler_type": visitor_info.get("crawler_name"),
            "is_bot": visitor_info.get("is_crawler"),
            "country": event_country,
            "city": event_city,
            "tracking_method": "javascript",
        }

        event_payload = {
            "session_id": effective_session_id,
            "visit_id": linked_visit.id if linked_visit else None,
            "client_id": client_id,
            "event_type": event_type,
            "page_url": page_url[:2000] if page_url else None,
            "referrer": referrer[:2000] if referrer else None,
            "path": page_info.get("path"),
            "page_domain": page_domain,
            "referrer_domain": referrer_domain,
            "tracking_id": tracking_id,
            "source": utm_info.get("source"),
            "medium": utm_info.get("medium"),
            "campaign": utm_info.get("campaign"),
            "event_data": enriched_data,
            "client_side_timezone": client_side_data.get('timezone') if client_side_data else None,
            "client_side_language": client_side_data.get('language') if client_side_data else None,
            "client_side_screen_resolution": client_side_data.get('screen_resolution') if client_side_data else None,
            "client_side_viewport_size": client_side_data.get('viewport_size') if client_side_data else None,
            "client_side_device_memory": client_side_data.get('device_memory') if client_side_data else None,
            "client_side_connection_type": client_side_data.get('connection_type') if client_side_data else None,
            "message_id": message_id,
        }
        if occurred_at:
            try:
                event_payload["timestamp"] = datetime.fromisoformat(occurred_at)
            except (ValueError, TypeError):
                pass

        event_id = None
        queued = False
        is_real_form = client_id and event_type == "form_submit" and is_real_form_submit(enriched_data)

        if is_real_form:
            try:
                event = VisitEvent(**event_payload)
                db.add(event)
                await db.commit()
                await db.refresh(event)
                event_id = event.id
            except IntegrityError:
                await db.rollback()
                logger.info("Duplicate form_submit message_id skipped", message_id=message_id)
            if not settings.rabbitmq_enabled:
                try:
                    await job_runner.enqueue("recompute_journey", {"client_id": client_id}, dedup_key=client_id)
                except Exception as e:
                    logger.error("Failed to enqueue recompute_journey", client_id=client_id, error=str(e))
        elif event_batcher.enabled:
            queued = await event_batcher.enqueue(event_payload)
            if not queued:
                event = VisitEvent(**event_payload)
                db.add(event)
                await db.commit()
                await db.refresh(event)
                event_id = event.id
        else:
            event = VisitEvent(**event_payload)
            db.add(event)
            await db.commit()
            await db.refresh(event)
            event_id = event.id

        if linked_visit:
            try:
                changed = False
                if geo_info:
                    if not linked_visit.country and geo_info.get("country_code"):
                        linked_visit.country = geo_info.get("country_code"); changed = True
                    if not linked_visit.city and geo_info.get("city"):
                        linked_visit.city = geo_info.get("city"); changed = True
                if tracking_id and not linked_visit.tracking_id:
                    linked_visit.tracking_id = tracking_id; changed = True
                if client_side_data:
                    if not linked_visit.client_side_timezone and client_side_data.get('timezone'):
                        linked_visit.client_side_timezone = client_side_data.get('timezone'); changed = True
                    if not linked_visit.client_side_language and client_side_data.get('language'):
                        linked_visit.client_side_language = client_side_data.get('language'); changed = True
                    if not linked_visit.client_side_screen_resolution and client_side_data.get('screen_resolution'):
                        linked_visit.client_side_screen_resolution = client_side_data.get('screen_resolution'); changed = True
                    if not linked_visit.client_side_viewport_size and client_side_data.get('viewport_size'):
                        linked_visit.client_side_viewport_size = client_side_data.get('viewport_size'); changed = True
                    if not linked_visit.client_side_device_memory and client_side_data.get('device_memory'):
                        linked_visit.client_side_device_memory = client_side_data.get('device_memory'); changed = True
                    if not linked_visit.client_side_connection_type and client_side_data.get('connection_type'):
                        linked_visit.client_side_connection_type = client_side_data.get('connection_type'); changed = True
                if changed:
                    logger.info("Visit client-side data backfilled", visit_id=linked_visit.id)
                    db.add(linked_visit)
                    await db.commit()
            except Exception as e:
                logger.error("Failed to backfill visit client-side data", error=str(e), visit_id=linked_visit.id if linked_visit else None)
                await db.rollback()

        logger.info(
            "Event tracked",
            event_id=event_id,
            queued=queued,
            event_type=event_type,
            page_url=page_url,
            visit_id=linked_visit.id if linked_visit else None,
        )

        event_country = None
        try:
            event_country = session_row.country if session_row else None
        except Exception:
            pass

        return {
            "event_id": event_id,
            "queued": queued,
            "needs_enrichment": bool(is_real_form),
            "session_id": effective_session_id,
            "visit_id": linked_visit.id if linked_visit else None,
            "client_id": client_id,
            "country": event_country,
        }

    async def get_visit_by_id(self, db: AsyncSession, visit_id: int) -> Optional[Visit]:
        result = await db.execute(select(Visit).where(Visit.id == visit_id))
        return result.scalar_one_or_none()

    async def get_recent_visits(
        self,
        db: AsyncSession,
        limit: int = 100,
        crawler_type: Optional[str] = None,
        hours: int = 24
    ) -> List[Visit]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        stmt = select(Visit).where(Visit.timestamp >= cutoff)
        if crawler_type:
            stmt = stmt.where(Visit.crawler_type == crawler_type)
        result = await db.execute(stmt.order_by(Visit.timestamp.desc()).limit(limit))
        return result.scalars().all()

    async def get_session_stats(
        self,
        db: AsyncSession,
        session_id: str
    ) -> Dict[str, Any]:
        result = await db.execute(select(VisitSession).where(VisitSession.id == session_id))
        session = result.scalar_one_or_none()

        if not session:
            return {}

        result = await db.execute(select(Visit).where(Visit.session_id == session_id))
        visits = result.scalars().all()

        return {
            "session_id": session.id,
            "total_visits": len(visits),
            "first_visit": session.first_visit,
            "last_visit": session.last_visit,
            "country": session.country_name,
            "city": session.city,
            "unique_domains": len(set(v.page_domain for v in visits if v.page_domain)),
            "unique_paths": len(set(v.path for v in visits if v.path))
        }
