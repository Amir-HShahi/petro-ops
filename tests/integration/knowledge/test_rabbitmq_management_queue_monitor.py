import time
from collections.abc import Callable
from urllib.parse import urlsplit, urlunsplit

import pika
import pytest
from pika.adapters.blocking_connection import BlockingChannel

from offline_rag.knowledge.application.ports import IngestionLane, IngestionQueueDepth
from offline_rag.knowledge.infrastructure.errors import QueueMonitorUnavailableError
from offline_rag.knowledge.infrastructure.rabbitmq_management_queue_monitor import (
    INGESTION_QUEUES,
    RabbitMqManagementQueueMonitor,
)
from offline_rag.knowledge.infrastructure.rabbitmq_topology import (
    DEAD_LETTER_QUEUE,
    INGESTION_EXCHANGE,
    QUEUE_BY_LANE,
    message_body,
    message_properties,
)
from offline_rag.settings import Settings

pytestmark = pytest.mark.integration

# The management plugin refreshes its counts every 5 s by default.
WAIT_S = 20
TEXT_QUEUE = QUEUE_BY_LANE[IngestionLane.TEXT]
VISION_QUEUE = QUEUE_BY_LANE[IngestionLane.VISION]


@pytest.fixture
def management_url() -> str:
    return Settings().rabbitmq_management_url


@pytest.fixture
def monitor(
    management_url: str, rabbitmq_url: str, channel: BlockingChannel
) -> RabbitMqManagementQueueMonitor:
    opened = RabbitMqManagementQueueMonitor(
        management_url, virtual_host=pika.URLParameters(rabbitmq_url).virtual_host
    )
    try:
        opened.get_queue_depths()
    except QueueMonitorUnavailableError as error:
        pytest.skip(f"The management API at RABBITMQ_MANAGEMENT_URL is not reachable: {error!r}")
    return opened


def _publish(channel: BlockingChannel, count: int) -> None:
    for number in range(count):
        outbox_id = f"m{number}"
        channel.basic_publish(
            INGESTION_EXCHANGE,
            IngestionLane.TEXT.value,
            message_body(ingestion_id="ing-1", outbox_id=outbox_id),
            message_properties(outbox_id=outbox_id, attempt=1),
        )


def _depth_until(
    monitor: RabbitMqManagementQueueMonitor,
    queue: str,
    is_reached: Callable[[IngestionQueueDepth], bool],
) -> IngestionQueueDepth:
    deadline = time.monotonic() + WAIT_S
    while True:
        depth = next(d for d in monitor.get_queue_depths() if d.queue == queue)
        if is_reached(depth) or time.monotonic() > deadline:
            return depth
        time.sleep(0.5)


def _with_password(url: str, password: str) -> str:
    parts = urlsplit(url)
    netloc = f"{parts.username}:{password}@{parts.hostname}:{parts.port}"
    return urlunsplit(parts._replace(netloc=netloc))


def test_every_ingestion_queue_is_listed_in_order_when_read(
    monitor: RabbitMqManagementQueueMonitor,
):
    depths = monitor.get_queue_depths()

    assert [depth.queue for depth in depths] == list(INGESTION_QUEUES)
    assert [depth.queue for depth in depths] == [
        "ingestion",
        "ingestion.vision",
        "ingestion.retry",
        "ingestion.dlq",
    ]


def test_waiting_messages_are_counted_when_published_to_a_queue(
    monitor: RabbitMqManagementQueueMonitor, channel: BlockingChannel
):
    _publish(channel, 3)

    depth = _depth_until(monitor, TEXT_QUEUE, lambda depth: depth.messages_ready == 3)

    assert depth.messages_ready == 3
    assert depth.messages_unacked == 0


def test_message_in_progress_is_counted_when_a_worker_has_not_acked_it(
    monitor: RabbitMqManagementQueueMonitor, channel: BlockingChannel
):
    _publish(channel, 2)
    method, _properties, _body = channel.basic_get(TEXT_QUEUE, auto_ack=False)
    assert method is not None

    depth = _depth_until(monitor, TEXT_QUEUE, lambda depth: depth.messages_unacked == 1)

    assert (depth.messages_ready, depth.messages_unacked) == (1, 1)
    channel.basic_nack(method.delivery_tag, requeue=True)


def test_consumers_are_counted_when_a_worker_subscribes(
    monitor: RabbitMqManagementQueueMonitor, channel: BlockingChannel
):
    channel.basic_consume(VISION_QUEUE, lambda *_: None)

    depth = _depth_until(monitor, VISION_QUEUE, lambda depth: depth.consumers == 1)

    assert depth.consumers == 1


def test_queue_counts_as_empty_when_the_broker_does_not_have_it_yet(
    monitor: RabbitMqManagementQueueMonitor, channel: BlockingChannel
):
    channel.queue_delete(DEAD_LETTER_QUEUE)

    depth = next(d for d in monitor.get_queue_depths() if d.queue == DEAD_LETTER_QUEUE)

    assert depth == IngestionQueueDepth(
        queue=DEAD_LETTER_QUEUE, messages_ready=0, messages_unacked=0, consumers=0
    )


def test_monitor_is_unavailable_when_the_password_is_wrong(
    monitor: RabbitMqManagementQueueMonitor, management_url: str, rabbitmq_url: str
):
    wrong = RabbitMqManagementQueueMonitor(
        _with_password(management_url, "wrong-password"),
        virtual_host=pika.URLParameters(rabbitmq_url).virtual_host,
    )

    with pytest.raises(QueueMonitorUnavailableError) as caught:
        wrong.get_queue_depths()

    assert caught.value.code == "KNOWLEDGE_QUEUE_MONITOR_UNAVAILABLE"


def test_monitor_is_unavailable_when_nothing_listens_on_the_port():
    # Port 9 (discard) is closed on a normal machine, so the connection is refused.
    unreachable = RabbitMqManagementQueueMonitor("http://user:secret@127.0.0.1:9", virtual_host="/")

    with pytest.raises(QueueMonitorUnavailableError):
        unreachable.get_queue_depths()
