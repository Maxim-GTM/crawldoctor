"""Unit tests for F32: oversized visitor values and the consumer's failure path.

No server or Postgres needed (the async-session test uses in-memory SQLite):
    pytest tests/test_ingest_robustness.py
"""
import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import DataError, IntegrityError, MissingGreenlet, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.visit import Visit, VisitEvent, VisitSession, _fit_string_attrs, fit_to_columns
from app.mq.consumers.core_consumer import CoreConsumer, is_permanent
from app.mq.topology import QUEUE_RAW_EVENTS, QUEUE_RAW_EVENTS_DLQ
from app.services.tracking import _rollback_and_reload

# The package re-exports a CoreConsumer instance under the module's name.
core_consumer = importlib.import_module("app.mq.consumers.core_consumer")

# The utm_source that overflowed visit_events.source on 2026-10-24 (107 chars).
LONG_SOURCE = "articles_multi-agent-system-reliability-failure-patterns-root-causes-and-production-validation-strategies"


def test_fit_to_columns_cuts_only_oversized_strings():
    assert len(LONG_SOURCE) > 100
    values = {
        "source": LONG_SOURCE,
        "medium": "cta_modal",
        "event_type": "x" * 80,  # String(50)
        "page_url": "https://www.getmaxim.ai/" + "a" * 3000,  # String(2000)
        "visit_id": 7,
        "event_data": {"source": LONG_SOURCE},
        "not_a_column": "y" * 500,
    }
    fitted = fit_to_columns(VisitEvent.__table__, values)

    assert fitted["source"] == LONG_SOURCE[:100]
    assert fitted["medium"] == "cta_modal"
    assert len(fitted["event_type"]) == 50
    assert len(fitted["page_url"]) == 2000
    assert fitted["visit_id"] == 7
    assert fitted["event_data"] == {"source": LONG_SOURCE}  # JSON is unbounded
    assert fitted["not_a_column"] == "y" * 500
    assert values["source"] == LONG_SOURCE  # input left alone


@pytest.mark.parametrize("model", [Visit, VisitEvent, VisitSession])
def test_orm_hook_fits_every_bounded_string(model):
    obj = model()
    mapper = sa_inspect(model)
    bounded = [a for a in mapper.column_attrs if getattr(a.columns[0].type, "length", None)]
    for attr in bounded:
        setattr(obj, attr.key, "z" * (attr.columns[0].type.length + 25))

    _fit_string_attrs(mapper, None, obj)

    for attr in bounded:
        assert len(getattr(obj, attr.key)) == attr.columns[0].type.length, attr.key


@pytest_asyncio.fixture
async def sqlite_session():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(VisitSession.__table__.create)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as db:
        db.add(VisitSession(id="s1", ip_address="203.0.113.9", country="IN"))
        await db.commit()
        yield db
    await engine.dispose()


@pytest.mark.asyncio
async def test_plain_rollback_then_attribute_read_raises_missing_greenlet(sqlite_session):
    """The failure F32 saw: rollback() expires the row, the next read is sync IO."""
    row = await sqlite_session.get(VisitSession, "s1")
    await sqlite_session.rollback()
    with pytest.raises(MissingGreenlet):
        _ = row.country


@pytest.mark.asyncio
async def test_rollback_and_reload_keeps_rows_readable(sqlite_session):
    row = await sqlite_session.get(VisitSession, "s1")
    fresh = VisitSession(id="s2", ip_address="203.0.113.10", country="US")
    sqlite_session.add(fresh)
    await sqlite_session.flush()

    await _rollback_and_reload(sqlite_session, row, fresh, None)

    assert row.country == "IN"
    assert fresh.country == "US"  # inserted in the rolled-back transaction: transient, values kept
    assert not sa_inspect(fresh).persistent


def test_permanent_classification():
    assert is_permanent(DataError("INSERT", {}, Exception("value too long for type character varying(100)")))
    assert is_permanent(KeyError("ip_address"))
    assert is_permanent(json.JSONDecodeError("Expecting value", "", 0))
    # Retried: connection drops, and races that the next attempt resolves.
    assert not is_permanent(OperationalError("SELECT 1", {}, Exception("server closed the connection")))
    assert not is_permanent(IntegrityError("INSERT", {}, Exception("duplicate key")))
    assert not is_permanent(MissingGreenlet("greenlet_spawn has not been called"))


def _consumer_and_message(retry_count=0):
    consumer = CoreConsumer()
    consumer._events_exchange = SimpleNamespace(publish=AsyncMock())
    consumer._dlx_exchange = SimpleNamespace(publish=AsyncMock())
    message = SimpleNamespace(
        body=json.dumps({"message_id": "m1"}).encode(),
        headers={"x-retry-count": retry_count} if retry_count else {},
        message_id="m1",
        ack=AsyncMock(),
        nack=AsyncMock(),
    )
    return consumer, message


@pytest.mark.asyncio
async def test_deterministic_failure_goes_straight_to_dlq():
    consumer, message = _consumer_and_message()
    exc = DataError("INSERT INTO visit_events ...", {"source": LONG_SOURCE}, Exception("value too long"))

    assert await consumer._handle_failure(message, exc) is True

    consumer._events_exchange.publish.assert_not_awaited()
    consumer._dlx_exchange.publish.assert_awaited_once()
    dlq_msg, = consumer._dlx_exchange.publish.await_args.args
    assert consumer._dlx_exchange.publish.await_args.kwargs["routing_key"] == QUEUE_RAW_EVENTS_DLQ
    assert dlq_msg.headers["x-failure-reason"].startswith("DataError: ")
    assert len(dlq_msg.headers["x-failure-reason"]) <= core_consumer._FAILURE_REASON_MAX


@pytest.mark.asyncio
async def test_transient_failure_is_retried_then_dead_lettered(monkeypatch):
    monkeypatch.setattr(core_consumer.settings, "rabbitmq_max_retries", 3)
    exc = OperationalError("SELECT 1", {}, Exception("connection reset"))

    consumer, message = _consumer_and_message(retry_count=0)
    assert await consumer._handle_failure(message, exc) is True
    retry_msg, = consumer._events_exchange.publish.await_args.args
    assert consumer._events_exchange.publish.await_args.kwargs["routing_key"] == QUEUE_RAW_EVENTS
    assert retry_msg.headers["x-retry-count"] == 1
    consumer._dlx_exchange.publish.assert_not_awaited()

    consumer, message = _consumer_and_message(retry_count=3)
    assert await consumer._handle_failure(message, exc) is True
    consumer._events_exchange.publish.assert_not_awaited()
    consumer._dlx_exchange.publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_message_is_acked_once_placed(monkeypatch):
    consumer, message = _consumer_and_message()
    monkeypatch.setattr(consumer, "_process", AsyncMock(side_effect=DataError("INSERT", {}, Exception("too long"))))

    await consumer._handle_message(message)

    consumer._dlx_exchange.publish.assert_awaited_once()
    message.ack.assert_awaited_once()
    message.nack.assert_not_awaited()


@pytest.mark.asyncio
async def test_message_is_nacked_to_dlx_when_dlq_publish_fails(monkeypatch):
    consumer, message = _consumer_and_message()
    consumer._dlx_exchange.publish.side_effect = ConnectionError("broker gone")
    monkeypatch.setattr(consumer, "_process", AsyncMock(side_effect=KeyError("ip_address")))

    await consumer._handle_message(message)

    message.ack.assert_not_awaited()
    message.nack.assert_awaited_once_with(requeue=False)
