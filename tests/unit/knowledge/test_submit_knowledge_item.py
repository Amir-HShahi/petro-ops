import hashlib

import pytest
from tests.fakes.knowledge import (
    FakeClock,
    FakeIdGenerator,
    FakeNodeDirectory,
    InMemoryEventPublisher,
    InMemoryKnowledgeIngestionRepository,
    InMemoryKnowledgeItemRepository,
    InMemorySourceFileStore,
)

from offline_rag.knowledge.application.commands import SubmitKnowledgeItem
from offline_rag.knowledge.application.errors import (
    KnowledgeItemNotFoundError,
    OwnerNodeNotFoundError,
    SourceFileTooLargeError,
)
from offline_rag.knowledge.application.ports import IngestionLane
from offline_rag.knowledge.application.submit_knowledge_item import (
    BYTES_PER_MB,
    SubmitKnowledgeItemHandler,
)
from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.errors import (
    EmptySourceFileError,
    UnsupportedDocumentFormatError,
)
from offline_rag.knowledge.domain.events import KnowledgeItemSubmitted, MetadataRecorded
from offline_rag.knowledge.domain.knowledge_ingestion import IngestionStatus
from offline_rag.knowledge.domain.knowledge_scope import ConfidentialityLevel, KnowledgeScope
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

PDF_CONTENT = b"%PDF-1.7\nriser R-3 wall thickness"
OWNER = NodeIdentifier("sp12_inspection_team")
MAX_FILE_MB = 1


@pytest.fixture
def repository() -> InMemoryKnowledgeItemRepository:
    return InMemoryKnowledgeItemRepository()


@pytest.fixture
def ingestions(repository: InMemoryKnowledgeItemRepository) -> InMemoryKnowledgeIngestionRepository:
    return InMemoryKnowledgeIngestionRepository(repository)


@pytest.fixture
def file_store() -> InMemorySourceFileStore:
    return InMemorySourceFileStore()


@pytest.fixture
def publisher() -> InMemoryEventPublisher:
    return InMemoryEventPublisher()


@pytest.fixture
def handler(
    ingestions: InMemoryKnowledgeIngestionRepository,
    file_store: InMemorySourceFileStore,
    publisher: InMemoryEventPublisher,
) -> SubmitKnowledgeItemHandler:
    return SubmitKnowledgeItemHandler(
        ingestion_repository=ingestions,
        node_directory=FakeNodeDirectory(["sp12_inspection_team", "platform_sp12"]),
        source_file_store=file_store,
        clock=FakeClock(),
        id_generator=FakeIdGenerator(),
        event_publisher=publisher,
        max_file_mb=MAX_FILE_MB,
    )


def _command(
    content: bytes = PDF_CONTENT,
    owner: NodeIdentifier = OWNER,
    file_name: str = "project_report_sp12_riser_r3_integrity.pdf",
) -> SubmitKnowledgeItem:
    return SubmitKnowledgeItem(
        owner_node_id=owner,
        source_file_name=file_name,
        content=content,
        scope=KnowledgeScope(confidentiality=ConfidentialityLevel.INTERNAL),
        metadata=MetadataRecord(document_type="project_report"),
    )


def test_item_is_stored_with_first_version_when_file_is_submitted(
    handler: SubmitKnowledgeItemHandler, repository: InMemoryKnowledgeItemRepository
):
    item_id = handler.submit(_command()).item_id

    item = repository.get_by_id(item_id)
    assert item_id == "ki-1"
    assert item.owner_node_id == OWNER
    assert item.active_version.sequence_number == 1
    assert item.active_version.document_format == DocumentFormat.PDF
    assert item.active_version.content_hash == hashlib.sha256(PDF_CONTENT).hexdigest()
    assert item.active_version.metadata.document_type == "project_report"


def test_original_file_is_kept_when_file_is_submitted(
    handler: SubmitKnowledgeItemHandler,
    repository: InMemoryKnowledgeItemRepository,
    file_store: InMemorySourceFileStore,
):
    item_id = handler.submit(_command()).item_id

    reference = repository.get_by_id(item_id).active_version.source_file_reference
    assert file_store.files[reference] == (
        "project_report_sp12_riser_r3_integrity.pdf",
        PDF_CONTENT,
    )


def test_submitted_and_metadata_events_are_published_when_file_is_submitted(
    handler: SubmitKnowledgeItemHandler, publisher: InMemoryEventPublisher
):
    handler.submit(_command())

    assert [type(event) for event in publisher.events] == [
        KnowledgeItemSubmitted,
        MetadataRecorded,
    ]


def test_each_submission_gets_its_own_item_when_same_file_is_submitted_twice(
    handler: SubmitKnowledgeItemHandler, repository: InMemoryKnowledgeItemRepository
):
    first_id = handler.submit(_command()).item_id
    second_id = handler.submit(_command()).item_id

    assert first_id != second_id
    assert len(repository.items) == 2


@pytest.mark.parametrize(
    ("command", "error"),
    [
        (_command(owner=NodeIdentifier("unknown_node")), OwnerNodeNotFoundError),
        (_command(content=b""), EmptySourceFileError),
        (
            _command(content=PDF_CONTENT.ljust(MAX_FILE_MB * BYTES_PER_MB + 1, b" ")),
            SourceFileTooLargeError,
        ),
        (
            _command(content=b"\x89PNG\r\n\x1a\n", file_name="photo.png"),
            UnsupportedDocumentFormatError,
        ),
    ],
)
def test_nothing_is_stored_or_published_when_submission_is_rejected(
    handler: SubmitKnowledgeItemHandler,
    repository: InMemoryKnowledgeItemRepository,
    file_store: InMemorySourceFileStore,
    publisher: InMemoryEventPublisher,
    ingestions: InMemoryKnowledgeIngestionRepository,
    command: SubmitKnowledgeItem,
    error: type[Exception],
):
    with pytest.raises(error):
        handler.submit(command)

    assert repository.items == {}
    assert file_store.files == {}
    assert publisher.events == []
    assert ingestions.ingestions == {}
    assert ingestions.messages == []


def test_ingestion_is_queued_for_a_text_worker_when_file_is_submitted(
    handler: SubmitKnowledgeItemHandler, ingestions: InMemoryKnowledgeIngestionRepository
):
    receipt = handler.submit(_command())

    ingestion = ingestions.get_by_id(receipt.ingestion_id)
    assert receipt.status == IngestionStatus.QUEUED
    assert (ingestion.item_id, ingestion.version_tag.value) == (receipt.item_id, "v1")
    assert [(message.ingestion_id, message.lane) for message in ingestions.messages] == [
        (receipt.ingestion_id, IngestionLane.TEXT)
    ]


def test_request_id_is_kept_on_the_ingestion_when_command_carries_one(
    handler: SubmitKnowledgeItemHandler, ingestions: InMemoryKnowledgeIngestionRepository
):
    command = SubmitKnowledgeItem(
        owner_node_id=OWNER,
        source_file_name="report.pdf",
        content=PDF_CONTENT,
        scope=KnowledgeScope(confidentiality=ConfidentialityLevel.INTERNAL),
        request_id="req-42",
    )

    receipt = handler.submit(command)

    assert ingestions.get_by_id(receipt.ingestion_id).request_id == "req-42"


def test_unknown_node_error_names_the_node_when_owner_is_not_registered(
    handler: SubmitKnowledgeItemHandler,
):
    with pytest.raises(OwnerNodeNotFoundError) as caught:
        handler.submit(_command(owner=NodeIdentifier("unknown_node")))

    assert caught.value.code == "KNOWLEDGE_OWNER_NODE_NOT_FOUND"
    assert caught.value.details == {"node_id": "unknown_node"}


def test_repository_raises_not_found_when_item_does_not_exist(
    repository: InMemoryKnowledgeItemRepository,
):
    with pytest.raises(KnowledgeItemNotFoundError) as caught:
        repository.get_by_id("ki-404")

    assert caught.value.code == "KNOWLEDGE_ITEM_NOT_FOUND"


def test_file_is_accepted_when_it_is_exactly_the_size_limit(
    handler: SubmitKnowledgeItemHandler, repository: InMemoryKnowledgeItemRepository
):
    content = PDF_CONTENT.ljust(MAX_FILE_MB * BYTES_PER_MB, b" ")

    item_id = handler.submit(_command(content=content)).item_id

    assert item_id in repository.items
