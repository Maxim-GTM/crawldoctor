"""RabbitMQ connection manager.

Holds a single RobustConnection (auto-reconnects on failure) and a channel
pool for the publisher.  Consumers get dedicated channels via get_consumer_channel().
"""
import asyncio
from typing import Optional

import aio_pika
import aio_pika.pool
import structlog

from app.config import settings

logger = structlog.get_logger()


class MQConnection:
    def __init__(self) -> None:
        self._connection: Optional[aio_pika.RobustConnection] = None
        self._channel_pool: Optional[aio_pika.pool.Pool] = None

    async def connect(self) -> None:
        self._connection = await aio_pika.connect_robust(
            settings.rabbitmq_url,
            reconnect_interval=5,
        )
        logger.info("RabbitMQ connected", url=settings.rabbitmq_url)

        async def _make_channel() -> aio_pika.Channel:
            assert self._connection is not None
            channel = await self._connection.channel()
            await channel.set_qos(prefetch_count=1)
            return channel

        self._channel_pool = aio_pika.pool.Pool(_make_channel, max_size=10)

    async def close(self) -> None:
        if self._channel_pool:
            await self._channel_pool.close()
        if self._connection:
            await self._connection.close()
        logger.info("RabbitMQ connection closed")

    async def acquire_channel(self) -> aio_pika.pool.PoolItemContextManager:
        """Acquire a pooled channel for publishing."""
        assert self._channel_pool is not None, "MQConnection not connected"
        return self._channel_pool.acquire()

    async def get_consumer_channel(self) -> aio_pika.Channel:
        """Open a dedicated channel for a consumer (not pooled)."""
        assert self._connection is not None, "MQConnection not connected"
        return await self._connection.channel()
