import json
import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from pika.adapters.blocking_connection import BlockingChannel

from offline_rag.knowledge.application.commands import RunIngestionStep
from offline_rag.knowledge.application.ports import IngestionLane, OutboxMessage
from offline_rag.knowledge.application.run_ingestion_step import IngestionStepOutcome
from offline_rag.knowledge.infrastructure.errors import MessageBrokerUnavailableError
from offline_rag.knowledge.infrastructure.rabbitmq_ingestion_consumer import (
    RabbitMqIngestionConsumer,
)
from offline_rag.knowledge.infrastructure.rabbitmq_ingestion_message_publisher import (
    RabbitMqIngestionMessagePublisher,
)
from offline_rag.knowledge.infrastructure.rabbitmq_topology import (
    DEAD_LETTER_QUEUE,
    QUEUE_BY_LANE,
    RETRY_QUEUE,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
WAIT_S = 10


def _message(outbox_id: str = "m1", lane: IngestionLane = IngestionLane.TEXT) -> OutboxMessage:
    return OutboxMessage(outbox_id=outbox_id, ingestion_id="ing-1", lane=lane, created_at=NOW)


@pytest.fixture
def publisher(rabbitmq_url: str) -> Iterator[RabbitMqIngestionMessagePublisher]:
    opened = RabbitMqIngestionMessagePublisher(rabbitmq_url)
    yield opened
    opened.close()


def _get(channel: BlockingChannel, queue: str) -> tuple[Any, Any, bytes] | None:
    method, properties, body = channel.basic_get(queue, auto_ack=True)
    return None if method is None else (method, properties, body)


def _consume_until(
    rabbitmq_url: str,
    lane: IngestionLane,
    run_step: Callable[[RunIngestionStep], IngestionStepOutcome],
    is_done: Callable[[], bool],
) -> None:
    consumer = RabbitMqIngestionConsumer(rabbitmq_url, lane=lane, prefetch_count=1, retry_delay_s=1)
    worker = threading.Thread(target=consumer.run, args=(run_step,), daemon=True)
    worker.start()
    deadline = time.monotonic() + WAIT_S
    while not is_done() and time.monotonic() < deadline:
        time.sleep(0.1)
    # Give the last settle a moment to reach the broker before stopping.
    time.sleep(0.3)
    consumer.stop()
    worker.join(WAIT_S)


def _wait_for(channel: BlockingChannel, queue: str) -> tuple[Any, Any, bytes] | None:
    deadline = time.monotonic() + WAIT_S
    while time.monotonic() < deadline:
        got = _get(channel, queue)
        if got is not None:
            return got
        time.sleep(0.1)
    return None


@pytest.mark.parametrize("lane", list(IngestionLane))
def test_published_message_reaches_the_queue_of_its_lane_when_broker_confirms(
    channel: BlockingChannel, publisher: RabbitMqIngestionMessagePublisher, lane: IngestionLane
):
    publisher.publish(_message(lane=lane))

    got = _wait_for(channel, QUEUE_BY_LANE[lane])
    assert got is not None
    _, properties, body = got
    assert json.loads(body) == {"ingestion_id": "ing-1", "outbox_id": "m1"}
    assert (properties.message_id, properties.headers, properties.delivery_mode) == (
        "m1",
        {"attempt": 1},
        2,
    )


def test_publish_raises_broker_unavailable_when_broker_cannot_be_reached():
    publisher = RabbitMqIngestionMessagePublisher(
        "amqp://guest:guest@127.0.0.1:1/%2F?connection_attempts=1&socket_timeout=1"
    )

    with pytest.raises(MessageBrokerUnavailableError):
        publisher.publish(_message())


def test_step_runs_and_message_is_acked_when_outcome_is_done(
    channel: BlockingChannel, publisher: RabbitMqIngestionMessagePublisher, rabbitmq_url: str
):
    publisher.publish(_message())
    seen: list[RunIngestionStep] = []

    def run_step(command: RunIngestionStep) -> IngestionStepOutcome:
        seen.append(command)
        return IngestionStepOutcome.DONE

    _consume_until(rabbitmq_url, IngestionLane.TEXT, run_step, lambda: bool(seen))

    assert seen == [RunIngestionStep(ingestion_id="ing-1", lane=IngestionLane.TEXT)]
    assert (
        channel.queue_declare(QUEUE_BY_LANE[IngestionLane.TEXT], passive=True).method.message_count
        == 0
    )


def test_message_comes_back_with_next_attempt_when_outcome_is_retry(
    channel: BlockingChannel, publisher: RabbitMqIngestionMessagePublisher, rabbitmq_url: str
):
    publisher.publish(_message())
    seen: list[RunIngestionStep] = []

    def run_step(command: RunIngestionStep) -> IngestionStepOutcome:
        seen.append(command)
        return IngestionStepOutcome.RETRY if command.attempt == 1 else IngestionStepOutcome.DONE

    _consume_until(rabbitmq_url, IngestionLane.TEXT, run_step, lambda: len(seen) >= 2)

    assert [command.attempt for command in seen] == [1, 2]
    assert _get(channel, RETRY_QUEUE) is None


def test_message_is_dead_lettered_with_its_lane_when_outcome_is_give_up(
    channel: BlockingChannel, publisher: RabbitMqIngestionMessagePublisher, rabbitmq_url: str
):
    publisher.publish(_message(lane=IngestionLane.VISION))
    seen: list[RunIngestionStep] = []

    def run_step(command: RunIngestionStep) -> IngestionStepOutcome:
        seen.append(command)
        return IngestionStepOutcome.GIVE_UP

    _consume_until(rabbitmq_url, IngestionLane.VISION, run_step, lambda: bool(seen))

    got = _wait_for(channel, DEAD_LETTER_QUEUE)
    assert got is not None
    assert got[1].headers == {
        "attempt": 1,
        "lane": "vision",
        "dead_letter_reason": "attempts_used_up",
    }


def test_malformed_message_is_dead_lettered_without_running_a_step_when_received(
    channel: BlockingChannel, rabbitmq_url: str
):
    channel.basic_publish("", QUEUE_BY_LANE[IngestionLane.TEXT], b"not json")
    seen: list[RunIngestionStep] = []

    def run_step(command: RunIngestionStep) -> IngestionStepOutcome:
        seen.append(command)
        return IngestionStepOutcome.DONE

    dead: list[tuple[Any, Any, bytes]] = []

    def is_dead_lettered() -> bool:
        got = _get(channel, DEAD_LETTER_QUEUE)
        if got is not None:
            dead.append(got)
        return bool(dead)

    _consume_until(rabbitmq_url, IngestionLane.TEXT, run_step, is_dead_lettered)

    assert seen == []
    assert dead[0][1].headers["dead_letter_reason"] == "malformed"
