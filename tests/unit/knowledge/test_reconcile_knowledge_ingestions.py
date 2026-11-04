from datetime import UTC, datetime, timedelta

import pytest
from tests.fakes.knowledge import (
    FakeClock,
    FakeIdGenerator,
    InMemoryKnowledgeIngestionRepository,
    InMemoryKnowledgeItemRepository,
    InMemoryOutbox,
)

from offline_rag.knowledge.application.commands import ReconcileKnowledgeIngestions
from offline_rag.knowledge.application.ports import IngestionLane, OutboxMessage
from offline_rag.knowledge.application.reconcile_knowledge_ingestions import (
    ReconcileKnowledgeIngestionsHandler,
)
from offline_rag.knowledge.domain.knowledge_ingestion import KnowledgeIngestion
from offline_rag.knowledge.domain.version_tag import VersionTag

NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
RECONCILE_AFTER_S = 1800
LONG_AGO = NOW - timedelta(seconds=RECONCILE_AFTER_S + 60)
RECENTLY = NOW - timedelta(seconds=RECONCILE_AFTER_S - 60)


@pytest.fixture
def ingestions() -> InMemoryKnowledgeIngestionRepository:
    return InMemoryKnowledgeIngestionRepository(InMemoryKnowledgeItemRepository())


@pytest.fixture
def handler(
    ingestions: InMemoryKnowledgeIngestionRepository,
) -> ReconcileKnowledgeIngestionsHandler:
    return ReconcileKnowledgeIngestionsHandler(
        ingestion_repository=ingestions,
        outbox=InMemoryOutbox(ingestions),
        clock=FakeClock(NOW),
        id_generator=FakeIdGenerator("resent"),
        reconcile_after_s=RECONCILE_AFTER_S,
    )


def _queued(
    ingestions: InMemoryKnowledgeIngestionRepository,
    ingestion_id: str = "ing-1",
    *,
    at: datetime = LONG_AGO,
    is_published: bool = True,
) -> KnowledgeIngestion:
    ingestion = KnowledgeIngestion.queue(
        ingestion_id=ingestion_id,
        item_id=f"ki-{ingestion_id}",
        version_tag=VersionTag("v1"),
        queued_at=at,
        request_id="r1",
    )
    message = OutboxMessage(
        outbox_id=f"m-{ingestion_id}",
        ingestion_id=ingestion_id,
        lane=IngestionLane.TEXT,
        created_at=at,
    )
    ingestions.save(ingestion, message)
    if is_published:
        ingestions.published_at[message.outbox_id] = at
    return ingestion


def _waiting_for_pages(ingestions: InMemoryKnowledgeIngestionRepository) -> KnowledgeIngestion:
    ingestion = _queued(ingestions)
    ingestion.start_extraction(LONG_AGO)
    ingestion.wait_for_page_reading(LONG_AGO)
    vision = OutboxMessage(
        outbox_id="m-vision", ingestion_id="ing-1", lane=IngestionLane.VISION, created_at=LONG_AGO
    )
    ingestions.save(ingestion, vision)
    ingestions.published_at[vision.outbox_id] = LONG_AGO
    return ingestion


def _new_messages(ingestions: InMemoryKnowledgeIngestionRepository) -> list[OutboxMessage]:
    return [message for message in ingestions.messages if message.outbox_id.startswith("resent")]


def test_text_message_is_added_when_queued_ingestion_waited_too_long(
    handler: ReconcileKnowledgeIngestionsHandler, ingestions: InMemoryKnowledgeIngestionRepository
):
    _queued(ingestions)

    resent = handler.reconcile(ReconcileKnowledgeIngestions())

    assert [ingestion.ingestion_id for ingestion in resent] == ["ing-1"]
    assert _new_messages(ingestions) == [
        OutboxMessage(
            outbox_id="resent-1", ingestion_id="ing-1", lane=IngestionLane.TEXT, created_at=NOW
        )
    ]


def test_vision_message_is_added_when_page_reading_waited_too_long(
    handler: ReconcileKnowledgeIngestionsHandler, ingestions: InMemoryKnowledgeIngestionRepository
):
    _waiting_for_pages(ingestions)

    handler.reconcile(ReconcileKnowledgeIngestions())

    assert [message.lane for message in _new_messages(ingestions)] == [IngestionLane.VISION]


def test_ingestion_itself_is_not_changed_when_message_is_resent(
    handler: ReconcileKnowledgeIngestionsHandler, ingestions: InMemoryKnowledgeIngestionRepository
):
    before = _queued(ingestions)

    handler.reconcile(ReconcileKnowledgeIngestions())

    assert ingestions.get_by_id("ing-1") == before


def test_nothing_is_resent_when_ingestion_changed_recently(
    handler: ReconcileKnowledgeIngestionsHandler, ingestions: InMemoryKnowledgeIngestionRepository
):
    _queued(ingestions, at=RECENTLY)

    assert handler.reconcile(ReconcileKnowledgeIngestions()) == []
    assert _new_messages(ingestions) == []


def test_nothing_is_resent_when_message_is_still_unpublished(
    handler: ReconcileKnowledgeIngestionsHandler, ingestions: InMemoryKnowledgeIngestionRepository
):
    _queued(ingestions, is_published=False)

    assert handler.reconcile(ReconcileKnowledgeIngestions()) == []


def test_message_is_resent_once_when_reconciler_runs_twice(
    handler: ReconcileKnowledgeIngestionsHandler, ingestions: InMemoryKnowledgeIngestionRepository
):
    _queued(ingestions)
    handler.reconcile(ReconcileKnowledgeIngestions())
    ingestions.published_at["resent-1"] = NOW

    handler.reconcile(ReconcileKnowledgeIngestions())

    assert len(_new_messages(ingestions)) == 1


def test_nothing_is_resent_when_ingestion_is_extracting(
    handler: ReconcileKnowledgeIngestionsHandler, ingestions: InMemoryKnowledgeIngestionRepository
):
    ingestion = _queued(ingestions)
    ingestion.start_extraction(LONG_AGO)
    ingestions.save(ingestion)

    assert handler.reconcile(ReconcileKnowledgeIngestions()) == []


@pytest.mark.parametrize("has_completed", [True, False])
def test_nothing_is_resent_when_ingestion_has_ended(
    handler: ReconcileKnowledgeIngestionsHandler,
    ingestions: InMemoryKnowledgeIngestionRepository,
    has_completed: bool,
):
    ingestion = _queued(ingestions)
    ingestion.start_extraction(LONG_AGO)
    if has_completed:
        ingestion.complete(blocks_for_review=0, now=LONG_AGO)
    else:
        ingestion.fail(failure_code="X", failure_detail="x", now=LONG_AGO)
    ingestions.save(ingestion)

    assert handler.reconcile(ReconcileKnowledgeIngestions()) == []


def test_only_max_ingestions_get_a_message_when_more_are_stalled(
    handler: ReconcileKnowledgeIngestionsHandler, ingestions: InMemoryKnowledgeIngestionRepository
):
    _queued(ingestions, "ing-old", at=LONG_AGO - timedelta(minutes=5))
    _queued(ingestions, "ing-new")

    resent = handler.reconcile(ReconcileKnowledgeIngestions(max_ingestions=1))

    assert [ingestion.ingestion_id for ingestion in resent] == ["ing-old"]
