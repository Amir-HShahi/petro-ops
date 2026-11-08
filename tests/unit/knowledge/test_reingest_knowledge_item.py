from datetime import UTC, datetime

import pytest
from tests.fakes.knowledge import (
    FakeClock,
    FakeIdGenerator,
    InMemoryKnowledgeIngestionRepository,
    InMemoryKnowledgeItemRepository,
)

from offline_rag.knowledge.application.commands import ReingestKnowledgeItem
from offline_rag.knowledge.application.errors import (
    IngestionAlreadyRunningError,
    KnowledgeItemNotFoundError,
)
from offline_rag.knowledge.application.ports import IngestionLane
from offline_rag.knowledge.application.reingest_knowledge_item import (
    ReingestKnowledgeItemHandler,
)
from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.errors import KnowledgeVersionNotFoundError
from offline_rag.knowledge.domain.knowledge_ingestion import IngestionStatus, KnowledgeIngestion
from offline_rag.knowledge.domain.knowledge_item import KnowledgeItem
from offline_rag.knowledge.domain.knowledge_scope import ConfidentialityLevel, KnowledgeScope
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
V1 = VersionTag("v1")


@pytest.fixture
def ingestions() -> InMemoryKnowledgeIngestionRepository:
    repository = InMemoryKnowledgeItemRepository()
    repository.add(
        KnowledgeItem.submit(
            item_id="ki-1",
            owner_node_id=NodeIdentifier("sp12_inspection_team"),
            scope=KnowledgeScope(confidentiality=ConfidentialityLevel.INTERNAL),
            metadata=MetadataRecord(),
            source_file_name="report.pdf",
            source_file_reference="stored.pdf",
            document_format=DocumentFormat.PDF,
            content_hash="hash",
            submitted_at=NOW,
        )
    )
    return InMemoryKnowledgeIngestionRepository(repository)


@pytest.fixture
def handler(ingestions: InMemoryKnowledgeIngestionRepository) -> ReingestKnowledgeItemHandler:
    return ReingestKnowledgeItemHandler(
        ingestion_repository=ingestions,
        repository=ingestions.item_repository,
        clock=FakeClock(NOW),
        id_generator=FakeIdGenerator("ing"),
    )


def _earlier_run(ingestions: InMemoryKnowledgeIngestionRepository, *, is_finished: bool) -> None:
    run = KnowledgeIngestion.queue(
        ingestion_id="old", item_id="ki-1", version_tag=V1, queued_at=NOW
    )
    if is_finished:
        run.fail(failure_code="X", failure_detail="x", now=NOW)
    ingestions.ingestions["old"] = run


@pytest.mark.parametrize("version_tag", [None, V1])
def test_active_or_given_version_is_queued_when_item_is_reingested(
    handler: ReingestKnowledgeItemHandler,
    ingestions: InMemoryKnowledgeIngestionRepository,
    version_tag: VersionTag | None,
):
    receipt = handler.reingest(
        ReingestKnowledgeItem(item_id="ki-1", version_tag=version_tag, request_id="req-1")
    )

    stored = ingestions.get_by_id(receipt.ingestion_id)
    assert (receipt.version_tag, receipt.status) == (V1, IngestionStatus.QUEUED)
    assert stored.request_id == "req-1"
    assert [(message.ingestion_id, message.lane) for message in ingestions.messages] == [
        (receipt.ingestion_id, IngestionLane.TEXT)
    ]


def test_new_run_is_queued_when_the_earlier_run_has_ended(
    handler: ReingestKnowledgeItemHandler, ingestions: InMemoryKnowledgeIngestionRepository
):
    _earlier_run(ingestions, is_finished=True)

    receipt = handler.reingest(ReingestKnowledgeItem(item_id="ki-1"))

    assert receipt.ingestion_id != "old"


def test_nothing_is_queued_when_an_earlier_run_is_still_going(
    handler: ReingestKnowledgeItemHandler, ingestions: InMemoryKnowledgeIngestionRepository
):
    _earlier_run(ingestions, is_finished=False)

    with pytest.raises(IngestionAlreadyRunningError) as caught:
        handler.reingest(ReingestKnowledgeItem(item_id="ki-1"))

    assert caught.value.details == {"item_id": "ki-1", "version_tag": "v1", "ingestion_id": "old"}
    assert ingestions.messages == []


@pytest.mark.parametrize(
    ("command", "error"),
    [
        (ReingestKnowledgeItem(item_id="ki-404"), KnowledgeItemNotFoundError),
        (
            ReingestKnowledgeItem(item_id="ki-1", version_tag=VersionTag("v9")),
            KnowledgeVersionNotFoundError,
        ),
    ],
)
def test_nothing_is_queued_when_item_or_version_is_missing(
    handler: ReingestKnowledgeItemHandler,
    ingestions: InMemoryKnowledgeIngestionRepository,
    command: ReingestKnowledgeItem,
    error: type[Exception],
):
    with pytest.raises(error):
        handler.reingest(command)

    assert ingestions.ingestions == {}
