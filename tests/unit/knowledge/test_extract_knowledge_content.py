from datetime import UTC, datetime

import pytest
from structlog.testing import capture_logs
from tests.fakes.knowledge import (
    FakeClock,
    FakeDocumentParser,
    InMemoryEventPublisher,
    InMemoryExtractedContentRepository,
    InMemoryKnowledgeItemRepository,
    InMemorySourceFileStore,
)

from offline_rag.knowledge.application.commands import ExtractKnowledgeContent
from offline_rag.knowledge.application.errors import KnowledgeItemNotFoundError
from offline_rag.knowledge.application.extract_knowledge_content import (
    ExtractKnowledgeContentHandler,
)
from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.errors import KnowledgeVersionNotFoundError
from offline_rag.knowledge.domain.events import (
    KnowledgeContentExtracted,
    KnowledgeItemSubmitted,
    MetadataRecorded,
)
from offline_rag.knowledge.domain.extracted_content import ContentBlock, ExtractedContent
from offline_rag.knowledge.domain.knowledge_item import KnowledgeItem
from offline_rag.knowledge.domain.knowledge_scope import ConfidentialityLevel, KnowledgeScope
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.knowledge.infrastructure.errors import DocumentExtractionError
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
    repository: InMemoryKnowledgeItemRepository,
    file_store: InMemorySourceFileStore,
    contents: InMemoryExtractedContentRepository,
    publisher: InMemoryEventPublisher,
    parser: FakeDocumentParser,
) -> ExtractKnowledgeContentHandler:
    return ExtractKnowledgeContentHandler(
        repository=repository,
        source_file_store=file_store,
        parser=parser,
        extracted_content_repository=contents,
        clock=FakeClock(NOW),
        event_publisher=publisher,
        min_page_text_chars=20,
    )


@pytest.fixture
def parser() -> FakeDocumentParser:
    return FakeDocumentParser(EXTRACTED)


@pytest.fixture
def handler(
    repository: InMemoryKnowledgeItemRepository,
    file_store: InMemorySourceFileStore,
    contents: InMemoryExtractedContentRepository,
    publisher: InMemoryEventPublisher,
    parser: FakeDocumentParser,
) -> ExtractKnowledgeContentHandler:
    return _handler(repository, file_store, contents, publisher, parser)


def _command(item_id: str = "ki-1", version_tag: str = "v1") -> ExtractKnowledgeContent:
    return ExtractKnowledgeContent(item_id=item_id, version_tag=VersionTag(version_tag))


def test_stored_file_is_parsed_with_its_format_when_version_is_extracted(
    handler: ExtractKnowledgeContentHandler, parser: FakeDocumentParser, item_id: str
):
    handler.extract(_command(item_id))

    assert parser.calls == [(PDF_FILE, DocumentFormat.PDF)]


def test_content_is_stored_and_returned_when_version_is_extracted(
    handler: ExtractKnowledgeContentHandler,
    contents: InMemoryExtractedContentRepository,
    item_id: str,
):
    result = handler.extract(_command(item_id))

    assert result == EXTRACTED
    assert contents.get(item_id, VersionTag("v1")) == EXTRACTED


def test_event_names_pages_for_the_lvm_when_version_is_extracted(
    handler: ExtractKnowledgeContentHandler, publisher: InMemoryEventPublisher, item_id: str
):
    handler.extract(_command(item_id))

    assert publisher.events == [
        KnowledgeContentExtracted(
            occurred_at=NOW,
            item_id=item_id,
            version_tag=VersionTag("v1"),
            block_count=1,
            pages_without_text=(2,),
        )
    ]


def test_extraction_replaces_the_old_result_when_run_again(
    repository: InMemoryKnowledgeItemRepository,
    file_store: InMemorySourceFileStore,
    contents: InMemoryExtractedContentRepository,
    publisher: InMemoryEventPublisher,
    item_id: str,
):
    _handler(repository, file_store, contents, publisher, FakeDocumentParser(EXTRACTED)).extract(
        _command(item_id)
    )
    newer = ExtractedContent(document_format=DocumentFormat.PDF, page_count=1, blocks=())

    _handler(repository, file_store, contents, publisher, FakeDocumentParser(newer)).extract(
        _command(item_id)
    )

    assert contents.get(item_id, VersionTag("v1")) == newer


@pytest.mark.parametrize(
    ("command", "error"),
    [
        (_command(item_id="ki-404"), KnowledgeItemNotFoundError),
        (_command(version_tag="v9"), KnowledgeVersionNotFoundError),
    ],
)
def test_nothing_is_stored_when_item_or_version_is_missing(
    handler: ExtractKnowledgeContentHandler,
    contents: InMemoryExtractedContentRepository,
    publisher: InMemoryEventPublisher,
    item_id: str,
    command: ExtractKnowledgeContent,
    error: type[Exception],
):
    with pytest.raises(error):
        handler.extract(command)

    assert contents.contents == {}
    assert publisher.events == []


def _submitted_event(item_id: str) -> KnowledgeItemSubmitted:
    return KnowledgeItemSubmitted(
        occurred_at=NOW,
        item_id=item_id,
        owner_node_id=NodeIdentifier("sp12_inspection_team"),
        version_tag=VersionTag("v1"),
        document_format=DocumentFormat.PDF,
        content_hash="hash",
    )


def test_first_version_is_extracted_when_an_item_is_submitted(
    handler: ExtractKnowledgeContentHandler,
    contents: InMemoryExtractedContentRepository,
    item_id: str,
):
    handler.on_knowledge_item_submitted(_submitted_event(item_id))

    assert contents.get(item_id, VersionTag("v1")) == EXTRACTED


def test_other_events_are_ignored_when_they_reach_the_submitted_policy(
    handler: ExtractKnowledgeContentHandler,
    parser: FakeDocumentParser,
    item_id: str,
):
    handler.on_knowledge_item_submitted(
        MetadataRecorded(
            occurred_at=NOW,
            item_id=item_id,
            version_tag=VersionTag("v1"),
            metadata=MetadataRecord(),
        )
    )

    assert parser.calls == []


def test_failed_extraction_is_logged_and_registration_stands_when_parsing_fails(
    repository: InMemoryKnowledgeItemRepository,
    file_store: InMemorySourceFileStore,
    contents: InMemoryExtractedContentRepository,
    publisher: InMemoryEventPublisher,
    item_id: str,
):
    parser = FakeDocumentParser(error=DocumentExtractionError("pdf"))
    handler = _handler(repository, file_store, contents, publisher, parser)

    with capture_logs() as logs:
        handler.on_knowledge_item_submitted(_submitted_event(item_id))

    assert repository.get_by_id(item_id).item_id == item_id
    assert contents.contents == {}
    assert logs == [
        {
            "event": "knowledge_content_extraction_failed",
            "log_level": "warning",
            "item_id": item_id,
            "version_tag": "v1",
            "code": "KNOWLEDGE_EXTRACTION_FAILED",
        }
    ]


def test_bug_is_not_hidden_when_extraction_fails_with_an_unexpected_error(
    repository: InMemoryKnowledgeItemRepository,
    file_store: InMemorySourceFileStore,
    contents: InMemoryExtractedContentRepository,
    publisher: InMemoryEventPublisher,
    item_id: str,
):
    parser = FakeDocumentParser(error=RuntimeError("parser bug"))
    handler = _handler(repository, file_store, contents, publisher, parser)

    with pytest.raises(RuntimeError, match="parser bug"):
        handler.on_knowledge_item_submitted(_submitted_event(item_id))
