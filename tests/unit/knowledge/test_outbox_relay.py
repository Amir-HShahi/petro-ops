from datetime import UTC, datetime, timedelta

import pytest
from tests.fakes.knowledge import (
    FakeClock,
    FakeIdGenerator,
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
from offline_rag.knowledge.application.reconcile_knowledge_ingestions import (
    ReconcileKnowledgeIngestionsHandler,
)
from offline_rag.knowledge.domain.knowledge_ingestion import KnowledgeIngestion
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.knowledge.infrastructure.errors import MessageBrokerUnavailableError
from offline_rag.knowledge.interface.outbox_relay import relay_pass

NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
RECONCILE_AFTER_S = 600
BATCH_SIZE = PublishOutboxMessages().max_messages


@pytest.fixture
def ingestions() -> InMemoryKnowledgeIngestionRepository:
    return InMemoryKnowledgeIngestionRepository(InMemoryKnowledgeItemRepository())


@pytest.fixture
def outbox(ingestions: InMemoryKnowledgeIngestionRepository) -> InMemoryOutbox:
    return InMemoryOutbox(ingestions)


def _message(number: int) -> OutboxMessage:
    return OutboxMessage(
        outbox_id=f"m{number}",
        ingestion_id=f"ing-{number}",
        lane=IngestionLane.TEXT,
        created_at=NOW - timedelta(seconds=number),
    )


def _relay_pass(
    ingestions: InMemoryKnowledgeIngestionRepository,
    outbox: InMemoryOutbox,
    publisher: FakeIngestionMessagePublisher,
) -> None:
    clock = FakeClock(NOW)
    relay_pass(
        ReconcileKnowledgeIngestionsHandler(
            ingestion_repository=ingestions,
            outbox=outbox,
            clock=clock,
            id_generator=FakeIdGenerator("resent"),
            reconcile_after_s=RECONCILE_AFTER_S,
        ),
        PublishOutboxMessagesHandler(outbox=outbox, publisher=publisher, clock=clock),
    )


def test_every_waiting_message_is_published_when_there_are_more_than_one_batch(
    ingestions: InMemoryKnowledgeIngestionRepository, outbox: InMemoryOutbox
):
    for number in range(BATCH_SIZE + 5):
        outbox.add(_message(number))
    publisher = FakeIngestionMessagePublisher()

    _relay_pass(ingestions, outbox, publisher)

    assert len(publisher.published) == BATCH_SIZE + 5
    assert outbox.find_unpublished(limit=1) == []


def test_resent_message_is_published_in_the_same_pass_when_an_ingestion_stalled(
    ingestions: InMemoryKnowledgeIngestionRepository, outbox: InMemoryOutbox
):
    queued_at = NOW - timedelta(seconds=RECONCILE_AFTER_S + 1)
    ingestions.ingestions["ing-1"] = KnowledgeIngestion.queue(
        ingestion_id="ing-1", item_id="ki-1", version_tag=VersionTag("v1"), queued_at=queued_at
    )
    publisher = FakeIngestionMessagePublisher()

    _relay_pass(ingestions, outbox, publisher)

    assert [message.ingestion_id for message in publisher.published] == ["ing-1"]


def test_messages_wait_for_the_next_pass_when_the_broker_is_down(
    ingestions: InMemoryKnowledgeIngestionRepository, outbox: InMemoryOutbox
):
    outbox.add(_message(1))
    publisher = FakeIngestionMessagePublisher(error=MessageBrokerUnavailableError("publish"))

    _relay_pass(ingestions, outbox, publisher)

    assert [message.outbox_id for message in outbox.find_unpublished(limit=10)] == ["m1"]
