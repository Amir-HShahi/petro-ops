from datetime import UTC, datetime

import pytest
from tests.fakes.knowledge import (
    FakeClock,
    FakeDocumentParser,
    FakeIdGenerator,
    FakeLvm,
    FakePageRenderer,
    FakeTableOcr,
    InMemoryEventPublisher,
    InMemoryExtractedContentRepository,
    InMemoryKnowledgeIngestionRepository,
    InMemoryKnowledgeItemRepository,
    InMemorySourceFileStore,
)

from offline_rag.knowledge.application.commands import RunIngestionStep
from offline_rag.knowledge.application.extract_knowledge_content import (
    ExtractKnowledgeContentHandler,
)
from offline_rag.knowledge.application.fail_knowledge_ingestion import (
    FailKnowledgeIngestionHandler,
)
from offline_rag.knowledge.application.ports import IngestionLane
from offline_rag.knowledge.application.read_pages_with_lvm import ReadPagesWithLvmHandler
from offline_rag.knowledge.application.run_ingestion_step import (
    IngestionStepOutcome,
    RunIngestionStepHandler,
)
from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.extracted_content import ContentBlock, ExtractedContent
from offline_rag.knowledge.domain.knowledge_ingestion import IngestionStatus, KnowledgeIngestion
from offline_rag.knowledge.domain.knowledge_item import KnowledgeItem
from offline_rag.knowledge.domain.knowledge_scope import ConfidentialityLevel, KnowledgeScope
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.knowledge.infrastructure.errors import (
    DocConverterUnavailableError,
    ModelUnavailableError,
)
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
MAX_ATTEMPTS = 3
TEXT_ONLY = ExtractedContent(
    document_format=DocumentFormat.PDF,
    page_count=1,
    blocks=(ContentBlock.paragraph(order=0, text="Wall loss on riser R-3.", page_number=1),),
)
SCANNED = ExtractedContent(document_format=DocumentFormat.PDF, page_count=1, blocks=())


@pytest.fixture
def items() -> InMemoryKnowledgeItemRepository:
    return InMemoryKnowledgeItemRepository()


@pytest.fixture
def ingestions(items: InMemoryKnowledgeItemRepository) -> InMemoryKnowledgeIngestionRepository:
    return InMemoryKnowledgeIngestionRepository(items)


@pytest.fixture
def file_store(items: InMemoryKnowledgeItemRepository) -> InMemorySourceFileStore:
    store = InMemorySourceFileStore()
    items.add(
        KnowledgeItem.submit(
            item_id="ki-1",
            owner_node_id=NodeIdentifier("sp12_inspection_team"),
            scope=KnowledgeScope(confidentiality=ConfidentialityLevel.INTERNAL),
            metadata=MetadataRecord(),
            source_file_name="riser.pdf",
            source_file_reference=store.save("riser.pdf", b"%PDF-1.7"),
            document_format=DocumentFormat.PDF,
            content_hash="hash",
            submitted_at=NOW,
        )
    )
    return store


@pytest.fixture
def contents() -> InMemoryExtractedContentRepository:
    return InMemoryExtractedContentRepository()


@pytest.fixture
def queued(ingestions: InMemoryKnowledgeIngestionRepository) -> KnowledgeIngestion:
    ingestion = KnowledgeIngestion.queue(
        ingestion_id="ing-1", item_id="ki-1", version_tag=VersionTag("v1"), queued_at=NOW
    )
    ingestions.save(ingestion)
    return ingestion


def _handler(
    ingestions: InMemoryKnowledgeIngestionRepository,
    items: InMemoryKnowledgeItemRepository,
    file_store: InMemorySourceFileStore,
    contents: InMemoryExtractedContentRepository,
    *,
    parser: FakeDocumentParser | None = None,
    lvm: FakeLvm | None = None,
) -> RunIngestionStepHandler:
    clock = FakeClock(NOW)
    publisher = InMemoryEventPublisher()
    return RunIngestionStepHandler(
        extract_handler=ExtractKnowledgeContentHandler(
            ingestion_repository=ingestions,
            repository=items,
            source_file_store=file_store,
            parser=parser or FakeDocumentParser(TEXT_ONLY),
            extracted_content_repository=contents,
            clock=clock,
            id_generator=FakeIdGenerator("msg"),
            event_publisher=publisher,
            min_page_text_chars=5,
        ),
        read_pages_handler=ReadPagesWithLvmHandler(
            ingestion_repository=ingestions,
            repository=items,
            source_file_store=file_store,
            extracted_content_repository=contents,
            page_renderer=FakePageRenderer(),
            lvm=lvm or FakeLvm(),
            table_ocr=FakeTableOcr(),
            clock=clock,
            event_publisher=publisher,
            min_page_text_chars=5,
        ),
        fail_handler=FailKnowledgeIngestionHandler(ingestion_repository=ingestions, clock=clock),
        max_attempts=MAX_ATTEMPTS,
    )


def _waiting_for_pages(
    ingestions: InMemoryKnowledgeIngestionRepository, contents: InMemoryExtractedContentRepository
) -> None:
    ingestion = ingestions.get_by_id("ing-1")
    ingestion.start_extraction(NOW)
    ingestion.wait_for_page_reading(NOW)
    ingestions.save(ingestion)
    contents.save("ki-1", VersionTag("v1"), SCANNED)


@pytest.mark.usefixtures("queued")
def test_text_message_is_done_when_extraction_completes(
    ingestions: InMemoryKnowledgeIngestionRepository,
    items: InMemoryKnowledgeItemRepository,
    file_store: InMemorySourceFileStore,
    contents: InMemoryExtractedContentRepository,
):
    handler = _handler(ingestions, items, file_store, contents)

    outcome = handler.run(RunIngestionStep(ingestion_id="ing-1", lane=IngestionLane.TEXT))

    assert outcome == IngestionStepOutcome.DONE
    assert ingestions.get_by_id("ing-1").status == IngestionStatus.COMPLETED


@pytest.mark.usefixtures("queued")
def test_vision_message_is_done_when_pages_are_read(
    ingestions: InMemoryKnowledgeIngestionRepository,
    items: InMemoryKnowledgeItemRepository,
    file_store: InMemorySourceFileStore,
    contents: InMemoryExtractedContentRepository,
):
    _waiting_for_pages(ingestions, contents)
    handler = _handler(ingestions, items, file_store, contents)

    outcome = handler.run(RunIngestionStep(ingestion_id="ing-1", lane=IngestionLane.VISION))

    assert outcome == IngestionStepOutcome.DONE
    assert ingestions.get_by_id("ing-1").status == IngestionStatus.COMPLETED


@pytest.mark.usefixtures("queued")
def test_message_is_retried_and_run_stays_open_when_a_dependency_is_down(
    ingestions: InMemoryKnowledgeIngestionRepository,
    items: InMemoryKnowledgeItemRepository,
    file_store: InMemorySourceFileStore,
    contents: InMemoryExtractedContentRepository,
):
    parser = FakeDocumentParser(error=DocConverterUnavailableError())
    handler = _handler(ingestions, items, file_store, contents, parser=parser)

    outcome = handler.run(
        RunIngestionStep(ingestion_id="ing-1", lane=IngestionLane.TEXT, attempt=MAX_ATTEMPTS - 1)
    )

    assert outcome == IngestionStepOutcome.RETRY
    assert ingestions.get_by_id("ing-1").status == IngestionStatus.EXTRACTING


@pytest.mark.usefixtures("queued")
def test_vision_message_is_retried_when_the_model_server_is_down(
    ingestions: InMemoryKnowledgeIngestionRepository,
    items: InMemoryKnowledgeItemRepository,
    file_store: InMemorySourceFileStore,
    contents: InMemoryExtractedContentRepository,
):
    _waiting_for_pages(ingestions, contents)
    lvm = FakeLvm(error=ModelUnavailableError("gemma4:12b-it-qat"))
    handler = _handler(ingestions, items, file_store, contents, lvm=lvm)

    outcome = handler.run(RunIngestionStep(ingestion_id="ing-1", lane=IngestionLane.VISION))

    assert outcome == IngestionStepOutcome.RETRY


@pytest.mark.usefixtures("queued")
def test_ingestion_fails_with_the_last_error_when_attempts_are_used_up(
    ingestions: InMemoryKnowledgeIngestionRepository,
    items: InMemoryKnowledgeItemRepository,
    file_store: InMemorySourceFileStore,
    contents: InMemoryExtractedContentRepository,
):
    parser = FakeDocumentParser(error=DocConverterUnavailableError())
    handler = _handler(ingestions, items, file_store, contents, parser=parser)

    outcome = handler.run(
        RunIngestionStep(ingestion_id="ing-1", lane=IngestionLane.TEXT, attempt=MAX_ATTEMPTS)
    )

    stored = ingestions.get_by_id("ing-1")
    assert outcome == IngestionStepOutcome.GIVE_UP
    assert (stored.status, stored.failure_code) == (
        IngestionStatus.FAILED,
        "KNOWLEDGE_DOC_CONVERTER_UNAVAILABLE",
    )


@pytest.mark.usefixtures("queued")
def test_retried_message_starts_the_extraction_over_when_run_is_extracting(
    ingestions: InMemoryKnowledgeIngestionRepository,
    items: InMemoryKnowledgeItemRepository,
    file_store: InMemorySourceFileStore,
    contents: InMemoryExtractedContentRepository,
):
    stopped = ingestions.get_by_id("ing-1")
    stopped.start_extraction(NOW)
    ingestions.save(stopped)
    handler = _handler(ingestions, items, file_store, contents)

    handler.run(RunIngestionStep(ingestion_id="ing-1", lane=IngestionLane.TEXT, attempt=2))

    assert ingestions.get_by_id("ing-1").status == IngestionStatus.COMPLETED


def test_message_is_done_when_its_ingestion_does_not_exist(
    ingestions: InMemoryKnowledgeIngestionRepository,
    items: InMemoryKnowledgeItemRepository,
    file_store: InMemorySourceFileStore,
    contents: InMemoryExtractedContentRepository,
):
    handler = _handler(ingestions, items, file_store, contents)

    outcome = handler.run(RunIngestionStep(ingestion_id="ing-404", lane=IngestionLane.TEXT))

    assert outcome == IngestionStepOutcome.DONE
