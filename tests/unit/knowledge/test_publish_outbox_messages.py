from datetime import UTC, datetime, timedelta

import pytest
from tests.fakes.knowledge import (
    FakeClock,
    FakeIngestionMessagePublisher,
    InMemoryKnowledgeIngestionRepository,
    InMemoryKnowledgeItemRepository,
    InMemoryOutbox,
)

from offline_rag.knowledge.application.commands import PublishOutboxMessages
from offline_rag.knowledge.application.ports import IngestionLane, OutboxMessage
from offline_rag.knowledge.application.publish_outbox_messages import (
    PublishOutboxMessagesHandler,
)
from offline_rag.knowledge.infrastructure.errors import MessageBrokerUnavailableError

NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)


def _message(outbox_id: str, minutes_ago: int, lane: IngestionLane = IngestionLane.TEXT):
    return OutboxMessage(
        outbox_id=outbox_id,
        ingestion_id=f"ing-{outbox_id}",
        lane=lane,
        created_at=NOW - timedelta(minutes=minutes_ago),
    )


@pytest.fixture
def ingestions() -> InMemoryKnowledgeIngestionRepository:
    return InMemoryKnowledgeIngestionRepository(InMemoryKnowledgeItemRepository())


@pytest.fixture
def outbox(ingestions: InMemoryKnowledgeIngestionRepository) -> InMemoryOutbox:
    return InMemoryOutbox(ingestions)


def _handler(outbox: InMemoryOutbox, publisher: FakeIngestionMessagePublisher):
    return PublishOutboxMessagesHandler(outbox=outbox, publisher=publisher, clock=FakeClock(NOW))


def test_waiting_messages_are_published_oldest_first_when_relay_runs(
    outbox: InMemoryOutbox, ingestions: InMemoryKnowledgeIngestionRepository
):
    outbox.add(_message("m2", minutes_ago=1, lane=IngestionLane.VISION))
    outbox.add(_message("m1", minutes_ago=5))
    publisher = FakeIngestionMessagePublisher()

    count = _handler(outbox, publisher).publish(PublishOutboxMessages())

    assert count == 2
    assert [message.outbox_id for message in publisher.published] == ["m1", "m2"]
    assert ingestions.published_at == {"m1": NOW, "m2": NOW}


def test_published_message_is_not_sent_again_when_relay_runs_twice(outbox: InMemoryOutbox):
    outbox.add(_message("m1", minutes_ago=5))
    publisher = FakeIngestionMessagePublisher()
    handler = _handler(outbox, publisher)
    handler.publish(PublishOutboxMessages())

    count = handler.publish(PublishOutboxMessages())

    assert count == 0
    assert [message.outbox_id for message in publisher.published] == ["m1"]


def test_only_max_messages_are_published_when_more_are_waiting(outbox: InMemoryOutbox):
    for minutes_ago, outbox_id in enumerate(["m3", "m2", "m1"]):
        outbox.add(_message(outbox_id, minutes_ago=minutes_ago))
    publisher = FakeIngestionMessagePublisher()

    count = _handler(outbox, publisher).publish(PublishOutboxMessages(max_messages=2))

    assert count == 2
    assert [message.outbox_id for message in outbox.find_unpublished(10)] == ["m3"]


def test_messages_after_the_failure_stay_unpublished_when_broker_fails(
    outbox: InMemoryOutbox, ingestions: InMemoryKnowledgeIngestionRepository
):
    for minutes_ago, outbox_id in [(3, "m1"), (2, "m2"), (1, "m3")]:
        outbox.add(_message(outbox_id, minutes_ago=minutes_ago))
    publisher = FakeIngestionMessagePublisher(
        error=MessageBrokerUnavailableError("publish"), fail_from=2
    )

    with pytest.raises(MessageBrokerUnavailableError):
        _handler(outbox, publisher).publish(PublishOutboxMessages())

    assert list(ingestions.published_at) == ["m1"]
    assert [message.outbox_id for message in outbox.find_unpublished(10)] == ["m2", "m3"]


def test_nothing_is_published_when_outbox_is_empty(outbox: InMemoryOutbox):
    publisher = FakeIngestionMessagePublisher()

    count = _handler(outbox, publisher).publish(PublishOutboxMessages())

    assert count == 0
    assert publisher.published == []
