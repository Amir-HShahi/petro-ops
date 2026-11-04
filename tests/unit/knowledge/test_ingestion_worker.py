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
from offline_rag.knowledge.domain.knowledge_ingestion import IngestionStatus, KnowledgeIngestion
from offline_rag.knowledge.domain.knowledge_item import KnowledgeItem
from offline_rag.knowledge.domain.knowledge_scope import ConfidentialityLevel, KnowledgeScope
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.knowledge.infrastructure.rabbitmq_ingestion_consumer import RunStep
from offline_rag.knowledge.interface.ingestion_worker import guard_step
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
COMMAND = RunIngestionStep(ingestion_id="ing-1", lane=IngestionLane.TEXT)


@pytest.fixture
def items() -> InMemoryKnowledgeItemRepository:
    return InMemoryKnowledgeItemRepository()


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
def ingestions(items: InMemoryKnowledgeItemRepository) -> InMemoryKnowledgeIngestionRepository:
    repository = InMemoryKnowledgeIngestionRepository(items)
    repository.save(
        KnowledgeIngestion.queue(
            ingestion_id="ing-1", item_id="ki-1", version_tag=VersionTag("v1"), queued_at=NOW
        )
    )
    return repository


@pytest.fixture
def run_step(
    items: InMemoryKnowledgeItemRepository,
    file_store: InMemorySourceFileStore,
    ingestions: InMemoryKnowledgeIngestionRepository,
) -> RunStep:
    clock = FakeClock(NOW)
    contents = InMemoryExtractedContentRepository()
    publisher = InMemoryEventPublisher()
    fail_handler = FailKnowledgeIngestionHandler(ingestion_repository=ingestions, clock=clock)
    run_handler = RunIngestionStepHandler(
        extract_handler=ExtractKnowledgeContentHandler(
            ingestion_repository=ingestions,
            repository=items,
            source_file_store=file_store,
            parser=FakeDocumentParser(error=RuntimeError("parser bug")),
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
            lvm=FakeLvm(),
            table_ocr=FakeTableOcr(),
            clock=clock,
            event_publisher=publisher,
            min_page_text_chars=5,
        ),
        fail_handler=fail_handler,
        max_attempts=3,
    )
    return guard_step(run_handler, fail_handler)


def test_message_is_dead_lettered_when_a_step_hits_a_bug(run_step: RunStep):
    assert run_step(COMMAND) == IngestionStepOutcome.GIVE_UP


def test_ingestion_fails_without_the_bug_details_when_a_step_hits_a_bug(
    run_step: RunStep, ingestions: InMemoryKnowledgeIngestionRepository
):
    run_step(COMMAND)

    stored = ingestions.get_by_id("ing-1")
    assert (stored.status, stored.failure_code) == (IngestionStatus.FAILED, "UNEXPECTED_ERROR")
    assert "parser bug" not in (stored.failure_detail or "")
