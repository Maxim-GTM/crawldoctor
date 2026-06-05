"""Core consumer — processes raw_events queue.

For each message:
  1. Check message_id in visit_events (idempotency) — ack + skip if already processed
  2. Call tracking_service.track_event() with message_id — creates session, visit, event
  3. On success: ack; if form_submit publishes to enrichment queue
  4. On transient failure: republish with incremented x-retry-count header
  5. After max_retries: publish to raw_events.dlq for manual inspection

A dedicated channel is used (not the publisher pool) to set per-consumer prefetch.
"""
import json
from typing import Any, Dict, Optional

import aio_pika
import structlog

from app.config import settings
from app.database import AsyncSessionLocal
from app.mq.connection import MQConnection
from app.mq.topology import (
    EXCHANGE_EVENTS,
    EXCHANGE_DLX,
    QUEUE_ENRICHMENT,
    QUEUE_RAW_EVENTS,
    QUEUE_RAW_EVENTS_DLQ,
)
from app.services.tracking import TrackingService

logger = structlog.get_logger()
tracking_service = TrackingService()


class CoreConsumer:
    def __init__(self) -> None:
        self._channel: Optional[aio_pika.Channel] = None
        self._events_exchange: Optional[aio_pika.Exchange] = None
        self._dlx_exchange: Optional[aio_pika.Exchange] = None

    async def start(self, connection: MQConnection) -> None:
        self._channel = await connection.get_consumer_channel()
        await self._channel.set_qos(prefetch_count=settings.rabbitmq_prefetch_count)

        self._events_exchange = await self._channel.get_exchange(EXCHANGE_EVENTS)
        self._dlx_exchange = await self._channel.get_exchange(EXCHANGE_DLX)

        queue = await self._channel.get_queue(QUEUE_RAW_EVENTS)
        await queue.consume(self._handle_message)
        logger.info("CoreConsumer started", queue=QUEUE_RAW_EVENTS)

    async def stop(self) -> None:
        if self._channel:
            await self._channel.close()
        logger.info("CoreConsumer stopped")

    async def _handle_message(self, message: aio_pika.IncomingMessage) -> None:
        try:
            payload = json.loads(message.body)
            result = await self._process(payload)

            if result.get("needs_enrichment") and result.get("client_id"):
                await self._publish_enrichment(payload, result)

            await message.ack()

        except Exception as exc:
            logger.error(
                "CoreConsumer processing failed",
                message_id=message.message_id,
                error=str(exc),
            )
            await self._handle_failure(message, exc)
            try:
                await message.nack(requeue=False)
            except Exception:
                pass  # already acked/nacked

    async def _process(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        message_id: Optional[str] = payload.get("message_id")

        # Idempotency check — skip if already written to DB
        if message_id and await self._already_processed(message_id):
            logger.info("Skipping duplicate message", message_id=message_id)
            return {}

        async with AsyncSessionLocal() as db:
            try:
                result = await tracking_service.track_event(
                    db=db,
                    ip_address=payload["ip_address"],
                    user_agent=payload["user_agent"],
                    event_type=payload["event_type"],
                    page_url=payload.get("page_url"),
                    referrer=payload.get("referrer"),
                    data=payload.get("data"),
                    visit_id=payload.get("visit_id"),
                    tracking_id=payload.get("tracking_id"),
                    client_id=payload.get("client_id"),
                    client_side_data=payload.get("client_side_data"),
                    message_id=message_id,
                )
                logger.debug(
                    "CoreConsumer processed event",
                    message_id=message_id,
                    event_type=payload.get("event_type"),
                    event_id=result.get("event_id"),
                )
                return result
            except Exception:
                await db.rollback()
                raise

    async def _already_processed(self, message_id: str) -> bool:
        from app.models.visit import VisitEvent
        from sqlalchemy import select
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(VisitEvent.id).where(VisitEvent.message_id == message_id)
                )
                return result.scalar_one_or_none() is not None
        except Exception:
            return False

    async def _publish_enrichment(
        self,
        raw_payload: Dict[str, Any],
        result: Dict[str, Any],
    ) -> None:
        enrichment_msg = {
            "message_id": raw_payload.get("message_id"),
            "event_id": result.get("event_id"),
            "session_id": result.get("session_id"),
            "visit_id": result.get("visit_id"),
            "client_id": raw_payload.get("client_id"),
            "event_type": raw_payload.get("event_type"),
            "ip_address": raw_payload.get("ip_address"),
            "country": result.get("country"),
        }
        try:
            assert self._events_exchange is not None
            await self._events_exchange.publish(
                aio_pika.Message(
                    body=json.dumps(enrichment_msg).encode(),
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    content_type="application/json",
                ),
                routing_key=QUEUE_ENRICHMENT,
            )
        except Exception as exc:
            logger.error("Failed to publish enrichment message", error=str(exc))

    async def _handle_failure(
        self, message: aio_pika.IncomingMessage, exc: Exception
    ) -> None:
        headers = dict(message.headers or {})
        retry_count = int(headers.get("x-retry-count", 0))

        if retry_count < settings.rabbitmq_max_retries:
            headers["x-retry-count"] = retry_count + 1
            try:
                assert self._events_exchange is not None
                await self._events_exchange.publish(
                    aio_pika.Message(
                        body=message.body,
                        headers=headers,
                        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                        content_type="application/json",
                        message_id=message.message_id,
                    ),
                    routing_key=QUEUE_RAW_EVENTS,
                )
                logger.warning(
                    "Retrying failed event",
                    message_id=message.message_id,
                    attempt=retry_count + 1,
                    max=settings.rabbitmq_max_retries,
                )
            except Exception as publish_exc:
                logger.error("Failed to republish for retry", error=str(publish_exc))
        else:
            headers["x-failure-reason"] = str(exc)
            try:
                assert self._dlx_exchange is not None
                await self._dlx_exchange.publish(
                    aio_pika.Message(
                        body=message.body,
                        headers=headers,
                        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                        content_type="application/json",
                        message_id=message.message_id,
                    ),
                    routing_key=QUEUE_RAW_EVENTS_DLQ,
                )
                logger.error(
                    "Event routed to DLQ after max retries",
                    message_id=message.message_id,
                    retries=retry_count,
                )
            except Exception as dlq_exc:
                logger.error("Failed to publish to DLQ", error=str(dlq_exc))
