"""Enrichment consumer — processes enrichment queue.

For each message (currently form_submit events from CoreConsumer):
  1. Trigger recompute_journey background job for the client
  2. Geo backfill: if the session/visit country is "XX" or null, re-run geo lookup
     and update the session and any linked visit

On success: ack.  On failure: nack → enrichment.dlq.
"""
import json
from typing import Any, Dict, Optional

import aio_pika
import structlog
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.mq.connection import MQConnection
from app.mq.topology import EXCHANGE_DLX, QUEUE_ENRICHMENT, QUEUE_ENRICHMENT_DLQ
from app.services.geo import GeoLocationService

logger = structlog.get_logger()
geo_service = GeoLocationService()

_UNKNOWN_COUNTRIES = {None, "XX", "Unknown", ""}


class EnrichmentConsumer:
    def __init__(self) -> None:
        self._channel: Optional[aio_pika.Channel] = None
        self._dlx_exchange: Optional[aio_pika.Exchange] = None

    async def start(self, connection: MQConnection) -> None:
        self._channel = await connection.get_consumer_channel()
        await self._channel.set_qos(prefetch_count=settings.rabbitmq_prefetch_count)

        self._dlx_exchange = await self._channel.get_exchange(EXCHANGE_DLX)

        queue = await self._channel.get_queue(QUEUE_ENRICHMENT)
        await queue.consume(self._handle_message)
        logger.info("EnrichmentConsumer started", queue=QUEUE_ENRICHMENT)

    async def stop(self) -> None:
        if self._channel:
            await self._channel.close()
        logger.info("EnrichmentConsumer stopped")

    async def _handle_message(self, message: aio_pika.IncomingMessage) -> None:
        async with message.process(requeue=False, ignore_processed=True):
            try:
                payload = json.loads(message.body)
                await self._process(payload)
            except Exception as exc:
                logger.error(
                    "EnrichmentConsumer processing failed",
                    message_id=message.message_id,
                    error=str(exc),
                    exc_info=True,
                )
                await self._route_to_dlq(message, exc)
                raise

    async def _process(self, payload: Dict[str, Any]) -> None:
        client_id: Optional[str] = payload.get("client_id")
        event_type: Optional[str] = payload.get("event_type")
        ip_address: Optional[str] = payload.get("ip_address")
        session_id: Optional[str] = payload.get("session_id")
        visit_id: Optional[int] = payload.get("visit_id")
        country: Optional[str] = payload.get("country")

        # Trigger lead recompute for form submissions
        if client_id and event_type == "form_submit":
            try:
                from app.background.runner import job_runner
                await job_runner.enqueue(
                    "recompute_journey",
                    {"client_id": client_id},
                    dedup_key=client_id,
                )
            except Exception as exc:
                logger.error("Failed to enqueue recompute_journey", client_id=client_id, error=str(exc))

        # Geo backfill if country is unknown
        if ip_address and country in _UNKNOWN_COUNTRIES and (session_id or visit_id):
            await self._backfill_geo(ip_address, session_id, visit_id)

    async def _backfill_geo(
        self,
        ip_address: str,
        session_id: Optional[str],
        visit_id: Optional[int],
    ) -> None:
        try:
            geo_info = await geo_service.get_location_info(ip_address)
        except Exception as exc:
            logger.warning("Geo backfill lookup failed", ip=ip_address, error=str(exc))
            return

        country = geo_info.get("country_code")
        if not country or country in _UNKNOWN_COUNTRIES:
            return

        db: Session = SessionLocal()
        try:
            from app.models.visit import Visit, VisitSession
            if session_id:
                session = db.query(VisitSession).filter(VisitSession.id == session_id).first()
                if session and session.country in _UNKNOWN_COUNTRIES:
                    session.country = country
                    session.city = geo_info.get("city")
                    session.country_name = geo_info.get("country_name")
                    session.latitude = geo_info.get("latitude")
                    session.longitude = geo_info.get("longitude")
                    session.timezone = geo_info.get("timezone")
                    session.isp = geo_info.get("isp")
                    session.organization = geo_info.get("organization")
                    session.asn = geo_info.get("asn")
                    db.add(session)

            if visit_id:
                visit = db.query(Visit).filter(Visit.id == visit_id).first()
                if visit and visit.country in _UNKNOWN_COUNTRIES:
                    visit.country = country
                    visit.city = geo_info.get("city")
                    db.add(visit)

            db.commit()
            logger.info("Geo backfill applied", session_id=session_id, visit_id=visit_id, country=country)
        except Exception as exc:
            db.rollback()
            logger.error("Geo backfill DB update failed", error=str(exc))
        finally:
            db.close()

    async def _route_to_dlq(
        self, message: aio_pika.IncomingMessage, exc: Exception
    ) -> None:
        headers = dict(message.headers or {})
        headers["x-failure-reason"] = str(exc)
        try:
            assert self._dlx_exchange is not None
            await self._dlx_exchange.publish(
                aio_pika.Message(
                    body=message.body,
                    headers=headers,
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    content_type="application/json",
                ),
                routing_key=QUEUE_ENRICHMENT_DLQ,
            )
            logger.error("Enrichment event routed to DLQ", message_id=message.message_id)
        except Exception as dlq_exc:
            logger.error("Failed to publish to enrichment DLQ", error=str(dlq_exc))
