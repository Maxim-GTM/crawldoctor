"""Declare RabbitMQ exchanges, queues, and DLQs.

Call declare_topology() once at startup after connecting.  All declarations
are idempotent — safe to call on reconnect.

Topology:
  crawldoctor.events  (direct)  ← publisher routes here
    → raw_events      (durable, DLX=crawldoctor.dlx, DLK=raw_events)
    → enrichment      (durable, DLX=crawldoctor.dlx, DLK=enrichment)

  crawldoctor.dlx     (direct)  ← dead letters land here
    → raw_events.dlq  (durable)
    → enrichment.dlq  (durable)
"""
import aio_pika


EXCHANGE_EVENTS = "crawldoctor.events"
EXCHANGE_DLX = "crawldoctor.dlx"

QUEUE_RAW_EVENTS = "raw_events"
QUEUE_ENRICHMENT = "enrichment"
QUEUE_RAW_EVENTS_DLQ = "raw_events.dlq"
QUEUE_ENRICHMENT_DLQ = "enrichment.dlq"


async def declare_topology(channel: aio_pika.Channel) -> None:
    events_exchange = await channel.declare_exchange(
        EXCHANGE_EVENTS,
        aio_pika.ExchangeType.DIRECT,
        durable=True,
    )
    dlx_exchange = await channel.declare_exchange(
        EXCHANGE_DLX,
        aio_pika.ExchangeType.DIRECT,
        durable=True,
    )

    # Main queues — dead-letter to DLX with matching routing key
    raw_events_queue = await channel.declare_queue(
        QUEUE_RAW_EVENTS,
        durable=True,
        arguments={
            "x-dead-letter-exchange": EXCHANGE_DLX,
            "x-dead-letter-routing-key": QUEUE_RAW_EVENTS_DLQ,
        },
    )
    enrichment_queue = await channel.declare_queue(
        QUEUE_ENRICHMENT,
        durable=True,
        arguments={
            "x-dead-letter-exchange": EXCHANGE_DLX,
            "x-dead-letter-routing-key": QUEUE_ENRICHMENT_DLQ,
        },
    )

    # Dead-letter queues — no consumers, inspected manually via management UI
    raw_events_dlq = await channel.declare_queue(QUEUE_RAW_EVENTS_DLQ, durable=True)
    enrichment_dlq = await channel.declare_queue(QUEUE_ENRICHMENT_DLQ, durable=True)

    # Bindings
    await raw_events_queue.bind(events_exchange, routing_key=QUEUE_RAW_EVENTS)
    await enrichment_queue.bind(events_exchange, routing_key=QUEUE_ENRICHMENT)
    await raw_events_dlq.bind(dlx_exchange, routing_key=QUEUE_RAW_EVENTS_DLQ)
    await enrichment_dlq.bind(dlx_exchange, routing_key=QUEUE_ENRICHMENT_DLQ)
