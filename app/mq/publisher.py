"""Event publisher — HTTP handler calls publish() to enqueue a raw tracking event.

Publisher confirms are enabled so publish() only returns after RabbitMQ has
durably accepted the message.  On any publish error the caller should fall
back to a direct service call.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

import aio_pika
import structlog

from app.mq.connection import MQConnection
from app.mq.topology import EXCHANGE_EVENTS, QUEUE_RAW_EVENTS

logger = structlog.get_logger()


class EventPublisher:
    def __init__(self, connection: MQConnection) -> None:
        self._connection = connection

    async def publish(self, payload: Dict[str, Any]) -> str:
        """Publish a raw tracking event.  Returns the assigned message_id."""
        message_id = str(uuid.uuid4())
        payload["message_id"] = message_id
        payload["received_at"] = datetime.now(timezone.utc).isoformat()

        body = json.dumps(payload).encode()
        message = aio_pika.Message(
            body=body,
            message_id=message_id,
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            content_type="application/json",
        )

        async with await self._connection.acquire_channel() as channel:
            await channel.set_qos(prefetch_count=1)
            exchange = await channel.get_exchange(EXCHANGE_EVENTS)
            await exchange.publish(message, routing_key=QUEUE_RAW_EVENTS)

        logger.debug("Event published to raw_events", message_id=message_id)
        return message_id
