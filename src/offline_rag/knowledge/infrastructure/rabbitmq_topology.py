"""The RabbitMQ exchanges, queues and message format of the ingestion workers (ADR 0005)."""

import json
from typing import Any

import pika
from pika.adapters.blocking_connection import BlockingChannel
from pika.exchange_type import ExchangeType

from offline_rag.knowledge.application.ports import IngestionLane

INGESTION_EXCHANGE = "ingestion.x"
# Fanout, so a retried message keeps its own routing key (`text`, `vision` or `chunking`), and
# the retry queue dead-letters it back to INGESTION_EXCHANGE under that key.
RETRY_EXCHANGE = "ingestion.retry.x"
QUEUE_BY_LANE = {
    IngestionLane.TEXT: "ingestion",
    IngestionLane.VISION: "ingestion.vision",
    IngestionLane.CHUNKING: "ingestion.chunking",
}
RETRY_QUEUE = "ingestion.retry"
DEAD_LETTER_QUEUE = "ingestion.dlq"
ATTEMPT_HEADER = "attempt"


def declare_ingestion_topology(channel: BlockingChannel) -> None:
    """Declare every exchange and queue the workers use. Declaring again changes nothing.

    The vision queue's longer consumer timeout is a broker policy, not declared
    here: RabbitMQ 4 refuses `x-consumer-timeout` on classic queues (ADR 0005).
    """
    channel.exchange_declare(INGESTION_EXCHANGE, ExchangeType.direct, durable=True)
    channel.exchange_declare(RETRY_EXCHANGE, ExchangeType.fanout, durable=True)
    for lane, queue in QUEUE_BY_LANE.items():
        channel.queue_declare(queue, durable=True)
        channel.queue_bind(queue, INGESTION_EXCHANGE, routing_key=lane.value)
    channel.queue_declare(
        RETRY_QUEUE, durable=True, arguments={"x-dead-letter-exchange": INGESTION_EXCHANGE}
    )
    channel.queue_bind(RETRY_QUEUE, RETRY_EXCHANGE)
    channel.queue_declare(DEAD_LETTER_QUEUE, durable=True)


def message_body(*, ingestion_id: str, outbox_id: str) -> bytes:
    """Return the JSON body of a worker message."""
    return json.dumps({"ingestion_id": ingestion_id, "outbox_id": outbox_id}).encode()


def message_properties(
    *, outbox_id: str, attempt: int, expiration_ms: int | None = None, **headers: Any
) -> pika.BasicProperties:
    """Return the properties of a persistent worker message.

    Args:
        outbox_id: The outbox row the message came from, used as its message id.
        attempt: How many times its step will have been tried when it runs.
        expiration_ms: How long it may wait in a queue, for the retry queue only.
        headers: Extra headers, such as why a message was dead-lettered.
    """
    return pika.BasicProperties(
        content_type="application/json",
        delivery_mode=pika.DeliveryMode.Persistent,
        message_id=outbox_id,
        headers={ATTEMPT_HEADER: attempt, **headers},
        expiration=None if expiration_ms is None else str(expiration_ms),
    )
