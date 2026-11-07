from datetime import UTC, datetime, timedelta

import pytest
from tests.fakes.knowledge import (
    FakeIngestionQueueMonitor,
    FakeNodeDirectory,
    InMemoryExtractedContentRepository,
    InMemoryKnowledgeIngestionRepository,
    InMemoryKnowledgeItemRepository,
    InMemoryOutbox,
)

from offline_rag.knowledge.application.errors import (
    ExtractedContentNotFoundError,
    KnowledgeIngestionNotFoundError,
)
from offline_rag.knowledge.application.knowledge_ingestion_queries import (
    KnowledgeIngestionQueries,
)
from offline_rag.knowledge.application.ports import (
    IngestionLane,
    IngestionQueueDepth,
    OutboxMessage,
)
from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.errors import KnowledgeVersionNotFoundError
from offline_rag.knowledge.domain.extracted_content import ContentBlock, ExtractedContent
from offline_rag.knowledge.domain.knowledge_ingestion import KnowledgeIngestion
from offline_rag.knowledge.domain.knowledge_item import KnowledgeItem
from offline_rag.knowledge.domain.knowledge_scope import ConfidentialityLevel, KnowledgeScope
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.knowledge.infrastructure.errors import QueueMonitorUnavailableError
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
V1 = VersionTag("v1")
CONTENT = ExtractedContent(
    document_format=DocumentFormat.DOCX,
    page_count=None,
    blocks=(ContentBlock.paragraph(order=0, text="Riser R-3 wall loss.", page_number=None),),
)


@pytest.fixture
def contents() -> InMemoryExtractedContentRepository:
    return InMemoryExtractedContentRepository()


DEPTHS = [
    IngestionQueueDepth(queue="ingestion", messages_ready=3, messages_unacked=1, consumers=2),
    IngestionQueueDepth(queue="ingestion.dlq", messages_ready=0, messages_unacked=0, consumers=0),
]


@pytest.fixture
def queue_monitor() -> FakeIngestionQueueMonitor:
    return FakeIngestionQueueMonitor(DEPTHS)


@pytest.fixture
def queries(
    contents: InMemoryExtractedContentRepository, queue_monitor: FakeIngestionQueueMonitor
) -> KnowledgeIngestionQueries:
    repository = InMemoryKnowledgeItemRepository()
    repository.add(
        KnowledgeItem.submit(
            item_id="ki-1",
            owner_node_id=NodeIdentifier("sp12_inspection_team"),
            scope=KnowledgeScope(confidentiality=ConfidentialityLevel.INTERNAL),
            metadata=MetadataRecord(),
            source_file_name="report.docx",
            source_file_reference="stored.docx",
            document_format=DocumentFormat.DOCX,
            content_hash="hash",
            submitted_at=NOW,
        )
    )
    ingestions = InMemoryKnowledgeIngestionRepository(repository)
    ingestions.ingestions["ing-1"] = KnowledgeIngestion.queue(
        ingestion_id="ing-1", item_id="ki-1", version_tag=V1, queued_at=NOW
    )
    ingestions.ingestions["ing-2"] = KnowledgeIngestion.queue(
        ingestion_id="ing-2",
        item_id="ki-1",
        version_tag=V1,
        queued_at=NOW + timedelta(minutes=5),
    )
    ingestions.messages.append(
        OutboxMessage(
            outbox_id="m-1", ingestion_id="ing-2", lane=IngestionLane.TEXT, created_at=NOW
        )
    )
    return KnowledgeIngestionQueries(
        ingestion_repository=ingestions,
        repository=repository,
        extracted_content_repository=contents,
        outbox=InMemoryOutbox(ingestions),
        node_directory=FakeNodeDirectory(["sp12_inspection_team", "platform_sp12"]),
        queue_monitor=queue_monitor,
    )


def test_ingestion_is_returned_when_it_exists(queries: KnowledgeIngestionQueries):
    assert queries.get_ingestion("ing-1").item_id == "ki-1"


def test_lookup_raises_not_found_when_ingestion_does_not_exist(queries: KnowledgeIngestionQueries):
    with pytest.raises(KnowledgeIngestionNotFoundError):
        queries.get_ingestion("ing-404")


@pytest.mark.parametrize("version_tag", [None, V1])
def test_content_of_active_or_given_version_is_returned_when_extracted(
    queries: KnowledgeIngestionQueries,
    contents: InMemoryExtractedContentRepository,
    version_tag: VersionTag | None,
):
    contents.save("ki-1", V1, CONTENT)

    assert queries.get_content("ki-1", version_tag) == (V1, CONTENT)


@pytest.mark.parametrize(
    ("version_tag", "error"),
    [(V1, ExtractedContentNotFoundError), (VersionTag("v9"), KnowledgeVersionNotFoundError)],
)
def test_content_lookup_raises_when_version_has_no_content_or_does_not_exist(
    queries: KnowledgeIngestionQueries, version_tag: VersionTag, error: type[Exception]
):
    with pytest.raises(error):
        queries.get_content("ki-1", version_tag)


def test_recent_ingestions_come_newest_first_with_their_file_when_listed(
    queries: KnowledgeIngestionQueries,
):
    recent = queries.list_recent_ingestions(10)

    assert [summary.ingestion.ingestion_id for summary in recent] == ["ing-2", "ing-1"]
    assert recent[0].source_file_name == "report.docx"
    assert recent[0].document_format == DocumentFormat.DOCX


def test_recent_ingestions_stop_at_the_limit_when_there_are_more(
    queries: KnowledgeIngestionQueries,
):
    assert [s.ingestion.ingestion_id for s in queries.list_recent_ingestions(1)] == ["ing-2"]


def test_queue_depths_come_from_the_monitor_when_read(queries: KnowledgeIngestionQueries):
    assert queries.get_queue_depths() == DEPTHS


def test_queue_depths_raise_when_the_monitor_is_unavailable(
    queries: KnowledgeIngestionQueries, queue_monitor: FakeIngestionQueueMonitor
):
    queue_monitor.error = QueueMonitorUnavailableError()

    with pytest.raises(QueueMonitorUnavailableError):
        queries.get_queue_depths()


def test_unpublished_messages_are_counted_when_the_relay_has_not_sent_them(
    queries: KnowledgeIngestionQueries,
):
    assert queries.count_unpublished_messages() == 1


def test_node_ids_are_listed_sorted_when_asked(queries: KnowledgeIngestionQueries):
    assert [node_id.value for node_id in queries.list_node_ids()] == [
        "platform_sp12",
        "sp12_inspection_team",
    ]
