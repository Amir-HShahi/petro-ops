from datetime import UTC, datetime

import pytest
from structlog.testing import capture_logs
from tests.fakes.knowledge import (
    FakeClock,
    FakeDocumentParser,
    FakeIdGenerator,
    InMemoryEventPublisher,
    InMemoryExtractedContentRepository,
    InMemoryKnowledgeIngestionRepository,
    InMemoryKnowledgeItemRepository,
    InMemorySourceFileStore,
)

from offline_rag.knowledge.application.commands import ExtractKnowledgeContent
from offline_rag.knowledge.application.errors import KnowledgeIngestionNotFoundError
from offline_rag.knowledge.application.extract_knowledge_content import (
    ExtractKnowledgeContentHandler,
)
from offline_rag.knowledge.application.ports import IngestionLane
from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.events import KnowledgeContentExtracted
from offline_rag.knowledge.domain.extracted_content import (
    ContentBlock,
    ContentSource,
    ExtractedContent,
)
from offline_rag.knowledge.domain.knowledge_ingestion import IngestionStatus, KnowledgeIngestion
from offline_rag.knowledge.domain.knowledge_item import KnowledgeItem
from offline_rag.knowledge.domain.knowledge_scope import ConfidentialityLevel, KnowledgeScope
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.knowledge.infrastructure.errors import (
    DocConverterUnavailableError,
    DocumentExtractionError,
)
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
PDF_FILE = b"%PDF-1.7 riser report"
EXTRACTED = ExtractedContent(
    document_format=DocumentFormat.PDF,
    page_count=2,
    blocks=(
        ContentBlock.paragraph(
            order=0, text="Wall loss on riser R-3 in the splash zone.", page_number=1
        ),
    ),
)


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
def contents() -> InMemoryExtractedContentRepository:
    return InMemoryExtractedContentRepository()


@pytest.fixture
def publisher() -> InMemoryEventPublisher:
    return InMemoryEventPublisher()


@pytest.fixture
def item_id(
    repository: InMemoryKnowledgeItemRepository, file_store: InMemorySourceFileStore
) -> str:
    reference = file_store.save("riser_report.pdf", PDF_FILE)
    item = KnowledgeItem.submit(
        item_id="ki-1",
        owner_node_id=NodeIdentifier("sp12_inspection_team"),
        scope=KnowledgeScope(confidentiality=ConfidentialityLevel.INTERNAL),
        metadata=MetadataRecord(),
        source_file_name="riser_report.pdf",
        source_file_reference=reference,
        document_format=DocumentFormat.PDF,
        content_hash="hash",
        submitted_at=NOW,
    )
    repository.add(item)
    return item.item_id


def _handler(
    ingestions: InMemoryKnowledgeIngestionRepository,
    repository: InMemoryKnowledgeItemRepository,
    file_store: InMemorySourceFileStore,
    contents: InMemoryExtractedContentRepository,
    publisher: InMemoryEventPublisher,
    parser: FakeDocumentParser,
) -> ExtractKnowledgeContentHandler:
    return ExtractKnowledgeContentHandler(
        ingestion_repository=ingestions,
        repository=repository,
        source_file_store=file_store,
        parser=parser,
        extracted_content_repository=contents,
        clock=FakeClock(NOW),
        id_generator=FakeIdGenerator("msg"),
        event_publisher=publisher,
        min_page_text_chars=20,
    )


@pytest.fixture
def parser() -> FakeDocumentParser:
    return FakeDocumentParser(EXTRACTED)


@pytest.fixture
def handler(
    ingestions: InMemoryKnowledgeIngestionRepository,
    repository: InMemoryKnowledgeItemRepository,
    file_store: InMemorySourceFileStore,
    contents: InMemoryExtractedContentRepository,
    publisher: InMemoryEventPublisher,
    parser: FakeDocumentParser,
) -> ExtractKnowledgeContentHandler:
    return _handler(ingestions, repository, file_store, contents, publisher, parser)


def _queue(
    ingestions: InMemoryKnowledgeIngestionRepository,
    item_id: str,
    *,
    ingestion_id: str = "ing-1",
    version_tag: str = "v1",
) -> str:
    ingestions.ingestions[ingestion_id] = KnowledgeIngestion.queue(
        ingestion_id=ingestion_id,
        item_id=item_id,
        version_tag=VersionTag(version_tag),
        queued_at=NOW,
    )
    return ingestion_id


@pytest.fixture
def ingestion_id(ingestions: InMemoryKnowledgeIngestionRepository, item_id: str) -> str:
    return _queue(ingestions, item_id)


def _command(ingestion_id: str = "ing-1") -> ExtractKnowledgeContent:
    return ExtractKnowledgeContent(ingestion_id=ingestion_id)


def test_stored_file_is_parsed_with_its_format_when_version_is_extracted(
    handler: ExtractKnowledgeContentHandler, parser: FakeDocumentParser, ingestion_id: str
):
    handler.extract(_command(ingestion_id))

    assert parser.calls == [(PDF_FILE, DocumentFormat.PDF)]


def test_content_is_stored_when_version_is_extracted(
    handler: ExtractKnowledgeContentHandler,
    contents: InMemoryExtractedContentRepository,
    item_id: str,
    ingestion_id: str,
):
    handler.extract(_command(ingestion_id))

    assert contents.get(item_id, VersionTag("v1")) == EXTRACTED


def test_event_names_pages_for_the_lvm_when_version_is_extracted(
    handler: ExtractKnowledgeContentHandler,
    publisher: InMemoryEventPublisher,
    item_id: str,
    ingestion_id: str,
):
    handler.extract(_command(ingestion_id))

    assert publisher.events == [
        KnowledgeContentExtracted(
            occurred_at=NOW,
            item_id=item_id,
            version_tag=VersionTag("v1"),
            block_count=1,
            pages_without_text=(2,),
        )
    ]


def test_ingestion_waits_for_the_vision_worker_when_pages_have_no_text(
    handler: ExtractKnowledgeContentHandler,
    ingestions: InMemoryKnowledgeIngestionRepository,
    ingestion_id: str,
):
    result = handler.extract(_command(ingestion_id))

    assert result.status == IngestionStatus.READING_PAGES
    assert ingestions.get_by_id(ingestion_id).status == IngestionStatus.READING_PAGES
    assert ingestions.get_by_id(ingestion_id).attempts == 1
    assert [(message.ingestion_id, message.lane) for message in ingestions.messages] == [
        (ingestion_id, IngestionLane.VISION)
    ]


def test_ingestion_completes_with_review_count_when_every_page_has_text(
    ingestions: InMemoryKnowledgeIngestionRepository,
    repository: InMemoryKnowledgeItemRepository,
    file_store: InMemorySourceFileStore,
    contents: InMemoryExtractedContentRepository,
    publisher: InMemoryEventPublisher,
    ingestion_id: str,
):
    flagged = ContentBlock.table(
        order=1,
        rows=[["a", "b"]],
        page_number=1,
        source=ContentSource.LVM,
        review_reason="OCR disagrees.",
    )
    one_page = ExtractedContent(
        document_format=DocumentFormat.PDF,
        page_count=1,
        blocks=(*EXTRACTED.blocks, flagged),
    )
    handler = _handler(
        ingestions, repository, file_store, contents, publisher, FakeDocumentParser(one_page)
    )

    result = handler.extract(_command(ingestion_id))

    assert result.status == IngestionStatus.COMPLETED
    assert result.blocks_for_review == 1
    assert ingestions.messages == []


def test_extraction_replaces_the_old_result_when_run_again(
    ingestions: InMemoryKnowledgeIngestionRepository,
    repository: InMemoryKnowledgeItemRepository,
    file_store: InMemorySourceFileStore,
    contents: InMemoryExtractedContentRepository,
    publisher: InMemoryEventPublisher,
    item_id: str,
    ingestion_id: str,
):
    _handler(
        ingestions, repository, file_store, contents, publisher, FakeDocumentParser(EXTRACTED)
    ).extract(_command(ingestion_id))
    newer = ExtractedContent(document_format=DocumentFormat.PDF, page_count=1, blocks=())
    second_run = _queue(ingestions, item_id, ingestion_id="ing-2")

    _handler(
        ingestions, repository, file_store, contents, publisher, FakeDocumentParser(newer)
    ).extract(_command(second_run))

    assert contents.get(item_id, VersionTag("v1")) == newer


def test_message_seen_again_changes_nothing_when_extraction_has_committed(
    handler: ExtractKnowledgeContentHandler,
    parser: FakeDocumentParser,
    ingestions: InMemoryKnowledgeIngestionRepository,
    ingestion_id: str,
):
    handler.extract(_command(ingestion_id))

    again = handler.extract(_command(ingestion_id))

    assert again.status == IngestionStatus.READING_PAGES
    assert len(parser.calls) == 1
    assert len(ingestions.messages) == 1


def test_extraction_starts_again_when_a_worker_stopped_mid_step(
    handler: ExtractKnowledgeContentHandler,
    ingestions: InMemoryKnowledgeIngestionRepository,
    ingestion_id: str,
):
    stopped = ingestions.get_by_id(ingestion_id)
    stopped.start_extraction(NOW)
    ingestions.save(stopped)

    result = handler.extract(ExtractKnowledgeContent(ingestion_id=ingestion_id, is_redelivery=True))

    assert result.status == IngestionStatus.READING_PAGES
    assert result.attempts == 2


def test_extraction_is_left_to_the_other_worker_when_a_fresh_message_finds_it_running(
    handler: ExtractKnowledgeContentHandler,
    parser: FakeDocumentParser,
    ingestions: InMemoryKnowledgeIngestionRepository,
    ingestion_id: str,
):
    running = ingestions.get_by_id(ingestion_id)
    running.start_extraction(NOW)
    ingestions.save(running)

    result = handler.extract(_command(ingestion_id))

    assert (result.status, result.attempts) == (IngestionStatus.EXTRACTING, 1)
    assert parser.calls == []


def test_only_the_first_worker_extracts_when_two_start_the_same_run(
    handler: ExtractKnowledgeContentHandler,
    parser: FakeDocumentParser,
    ingestions: InMemoryKnowledgeIngestionRepository,
    ingestion_id: str,
):
    ingestions.taken_by_another_worker.add(ingestion_id)

    result = handler.extract(_command(ingestion_id))

    assert result.status == IngestionStatus.QUEUED
    assert parser.calls == []
    assert ingestions.messages == []


def test_lookup_raises_not_found_when_ingestion_does_not_exist(
    handler: ExtractKnowledgeContentHandler,
):
    with pytest.raises(KnowledgeIngestionNotFoundError):
        handler.extract(_command("ing-404"))


@pytest.mark.parametrize(
    ("item_id_of_run", "version_tag", "code"),
    [
        ("ki-404", "v1", "KNOWLEDGE_ITEM_NOT_FOUND"),
        ("ki-1", "v9", "KNOWLEDGE_VERSION_NOT_FOUND"),
    ],
)
def test_ingestion_fails_and_nothing_is_stored_when_item_or_version_is_missing(
    handler: ExtractKnowledgeContentHandler,
    ingestions: InMemoryKnowledgeIngestionRepository,
    contents: InMemoryExtractedContentRepository,
    publisher: InMemoryEventPublisher,
    item_id: str,
    item_id_of_run: str,
    version_tag: str,
    code: str,
):
    run = _queue(ingestions, item_id_of_run, version_tag=version_tag)

    result = handler.extract(_command(run))

    assert (result.status, result.failure_code) == (IngestionStatus.FAILED, code)
    assert contents.contents == {}
    assert publisher.events == []


def test_failure_is_logged_and_registration_stands_when_parsing_fails(
    ingestions: InMemoryKnowledgeIngestionRepository,
    repository: InMemoryKnowledgeItemRepository,
    file_store: InMemorySourceFileStore,
    contents: InMemoryExtractedContentRepository,
    publisher: InMemoryEventPublisher,
    item_id: str,
    ingestion_id: str,
):
    parser = FakeDocumentParser(error=DocumentExtractionError("pdf"))
    handler = _handler(ingestions, repository, file_store, contents, publisher, parser)

    with capture_logs() as logs:
        handler.extract(_command(ingestion_id))

    stored = ingestions.get_by_id(ingestion_id)
    assert repository.get_by_id(item_id).item_id == item_id
    assert contents.contents == {}
    assert (stored.status, stored.failure_code) == (
        IngestionStatus.FAILED,
        "KNOWLEDGE_EXTRACTION_FAILED",
    )
    assert logs == [
        {
            "event": "knowledge_extraction_failed",
            "log_level": "warning",
            "ingestion_id": ingestion_id,
            "item_id": item_id,
            "code": "KNOWLEDGE_EXTRACTION_FAILED",
        }
    ]


def test_error_is_raised_for_a_retry_when_a_dependency_is_unavailable(
    ingestions: InMemoryKnowledgeIngestionRepository,
    repository: InMemoryKnowledgeItemRepository,
    file_store: InMemorySourceFileStore,
    contents: InMemoryExtractedContentRepository,
    publisher: InMemoryEventPublisher,
    ingestion_id: str,
):
    parser = FakeDocumentParser(error=DocConverterUnavailableError())
    handler = _handler(ingestions, repository, file_store, contents, publisher, parser)

    with pytest.raises(DocConverterUnavailableError):
        handler.extract(_command(ingestion_id))

    assert ingestions.get_by_id(ingestion_id).status == IngestionStatus.EXTRACTING


def test_bug_is_not_hidden_when_extraction_fails_with_an_unexpected_error(
    ingestions: InMemoryKnowledgeIngestionRepository,
    repository: InMemoryKnowledgeItemRepository,
    file_store: InMemorySourceFileStore,
    contents: InMemoryExtractedContentRepository,
    publisher: InMemoryEventPublisher,
    ingestion_id: str,
):
    parser = FakeDocumentParser(error=RuntimeError("parser bug"))
    handler = _handler(ingestions, repository, file_store, contents, publisher, parser)

    with pytest.raises(RuntimeError, match="parser bug"):
        handler.extract(_command(ingestion_id))
