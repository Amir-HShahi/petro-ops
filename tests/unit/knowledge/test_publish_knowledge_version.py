import hashlib
from datetime import UTC, datetime

import pytest
from tests.fakes.knowledge import (
    FakeClock,
    FakeIdGenerator,
    FakeIngestionQueueMonitor,
    FakeNodeDirectory,
    FakeTokenizer,
    InMemoryEventPublisher,
    InMemoryExtractedContentRepository,
    InMemoryKnowledgeChunkRepository,
    InMemoryKnowledgeIngestionRepository,
    InMemoryKnowledgeItemRepository,
    InMemoryOutbox,
    InMemorySourceFileStore,
    InMemoryVersionFingerprintRepository,
)

from offline_rag.knowledge.application.chunk_knowledge_content import (
    ChunkingSizes,
    ChunkKnowledgeContentHandler,
)
from offline_rag.knowledge.application.commands import (
    ChunkKnowledgeContent,
    PublishKnowledgeVersion,
)
from offline_rag.knowledge.application.errors import (
    KnowledgeItemNotFoundError,
    SourceFileTooLargeError,
)
from offline_rag.knowledge.application.knowledge_ingestion_queries import (
    KnowledgeIngestionQueries,
)
from offline_rag.knowledge.application.ports import IngestionLane
from offline_rag.knowledge.application.publish_knowledge_version import (
    PublishKnowledgeVersionHandler,
)
from offline_rag.knowledge.application.submit_knowledge_item import BYTES_PER_MB
from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.duplicate_detection import DuplicateDetector, DuplicateKind
from offline_rag.knowledge.domain.errors import (
    KnowledgeVersionChangeReasonMissingError,
    KnowledgeVersionUnchangedError,
    UnsupportedDocumentFormatError,
)
from offline_rag.knowledge.domain.events import (
    DuplicateDetected,
    KnowledgeVersionPublished,
    MetadataRecorded,
)
from offline_rag.knowledge.domain.extracted_content import ContentBlock, ExtractedContent
from offline_rag.knowledge.domain.knowledge_ingestion import IngestionStatus, KnowledgeIngestion
from offline_rag.knowledge.domain.knowledge_item import KnowledgeItem
from offline_rag.knowledge.domain.knowledge_scope import ConfidentialityLevel, KnowledgeScope
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
V1, V2 = VersionTag("v1"), VersionTag("v2")
TEAM = NodeIdentifier("sp12_inspection_team")
V1_FILE = b"PK\x03\x04 riser R-3 survey 2026 v1"
V2_FILE = b"PK\x03\x04 riser R-3 survey 2026 v2 with 3 more readings"
V1_METADATA = MetadataRecord(document_type="inspection_report")
MAX_FILE_MB = 1
DETECTOR = DuplicateDetector(
    overlap_chunk_similarity=0.4, ambiguous_from_similarity=0.25, min_chunk_share=0.2
)
SURVEY_TEXT = (
    "Wall loss on riser R-3 is concentrated in the splash zone between EL +5.0 m and EL +9.0 m, "
    "on the south-facing side, and the coating there has blistered and disbonded."
)


@pytest.fixture
def items() -> InMemoryKnowledgeItemRepository:
    repository = InMemoryKnowledgeItemRepository()
    for item_id, content in [("ki-1", V1_FILE), ("ki-other", V2_FILE)]:
        item = KnowledgeItem.submit(
            item_id=item_id,
            owner_node_id=TEAM,
            scope=KnowledgeScope(confidentiality=ConfidentialityLevel.INTERNAL),
            metadata=V1_METADATA,
            source_file_name=f"{item_id}.docx",
            source_file_reference=f"file-{item_id}",
            document_format=DocumentFormat.DOCX,
            content_hash=hashlib.sha256(content).hexdigest(),
            submitted_at=NOW,
        )
        # A stored item comes back without the events of its submission.
        item.pull_events()
        repository.add(item)
    return repository


@pytest.fixture
def ingestions(items: InMemoryKnowledgeItemRepository) -> InMemoryKnowledgeIngestionRepository:
    return InMemoryKnowledgeIngestionRepository(items)


@pytest.fixture
def file_store() -> InMemorySourceFileStore:
    return InMemorySourceFileStore()


@pytest.fixture
def publisher() -> InMemoryEventPublisher:
    return InMemoryEventPublisher()


@pytest.fixture
def fingerprints(items: InMemoryKnowledgeItemRepository) -> InMemoryVersionFingerprintRepository:
    return InMemoryVersionFingerprintRepository(items)


@pytest.fixture
def handler(
    ingestions: InMemoryKnowledgeIngestionRepository,
    items: InMemoryKnowledgeItemRepository,
    file_store: InMemorySourceFileStore,
    fingerprints: InMemoryVersionFingerprintRepository,
    publisher: InMemoryEventPublisher,
) -> PublishKnowledgeVersionHandler:
    return PublishKnowledgeVersionHandler(
        ingestion_repository=ingestions,
        repository=items,
        source_file_store=file_store,
        fingerprint_repository=fingerprints,
        detector=DETECTOR,
        clock=FakeClock(NOW),
        id_generator=FakeIdGenerator(),
        event_publisher=publisher,
        max_file_mb=MAX_FILE_MB,
    )


def _command(
    content: bytes = V2_FILE + b" changed",
    *,
    item_id: str = "ki-1",
    change_reason: str = "Adds 3 readings and a change note.",
    metadata: MetadataRecord | None = None,
) -> PublishKnowledgeVersion:
    return PublishKnowledgeVersion(
        item_id=item_id,
        source_file_name="inspection_sp12_riser_r3_2026_v2.docx",
        content=content,
        change_reason=change_reason,
        metadata=metadata,
    )


def test_new_version_becomes_active_with_the_change_reason_when_published(
    handler: PublishKnowledgeVersionHandler, items: InMemoryKnowledgeItemRepository
):
    receipt = handler.publish(_command())

    item = items.get_by_id("ki-1")
    assert receipt.version_tag == V2
    assert item.active_version.version_tag == V2
    assert item.active_version.previous_version_tag == V1
    assert item.active_version.change_reason == "Adds 3 readings and a change note."


def test_new_file_is_kept_when_a_version_is_published(
    handler: PublishKnowledgeVersionHandler,
    items: InMemoryKnowledgeItemRepository,
    file_store: InMemorySourceFileStore,
):
    handler.publish(_command())

    reference = items.get_by_id("ki-1").active_version.source_file_reference
    assert file_store.files[reference][1] == V2_FILE + b" changed"


def test_metadata_of_the_active_version_is_kept_when_none_is_given(
    handler: PublishKnowledgeVersionHandler, items: InMemoryKnowledgeItemRepository
):
    handler.publish(_command())

    assert items.get_by_id("ki-1").active_version.metadata == V1_METADATA


def test_given_metadata_is_recorded_when_a_version_is_published_with_it(
    handler: PublishKnowledgeVersionHandler, items: InMemoryKnowledgeItemRepository
):
    new_metadata = MetadataRecord(document_type="inspection_report", tags=("revised",))

    handler.publish(_command(metadata=new_metadata))

    assert items.get_by_id("ki-1").active_version.metadata == new_metadata


def test_ingestion_of_the_new_version_is_queued_for_a_text_worker_when_published(
    handler: PublishKnowledgeVersionHandler, ingestions: InMemoryKnowledgeIngestionRepository
):
    receipt = handler.publish(_command())

    ingestion = ingestions.get_by_id(receipt.ingestion_id)
    assert (ingestion.item_id, ingestion.version_tag, ingestion.status) == (
        "ki-1",
        V2,
        IngestionStatus.QUEUED,
    )
    assert [(message.ingestion_id, message.lane) for message in ingestions.messages] == [
        (receipt.ingestion_id, IngestionLane.TEXT)
    ]


def test_published_and_metadata_events_are_published_when_a_version_is_published(
    handler: PublishKnowledgeVersionHandler, publisher: InMemoryEventPublisher
):
    handler.publish(_command())

    assert [type(event) for event in publisher.events] == [
        KnowledgeVersionPublished,
        MetadataRecorded,
    ]


def test_exact_duplicate_is_flagged_and_published_when_the_file_is_another_items_file(
    handler: PublishKnowledgeVersionHandler,
    ingestions: InMemoryKnowledgeIngestionRepository,
    publisher: InMemoryEventPublisher,
):
    handler.publish(_command(V2_FILE))

    (flag,) = ingestions.flag_repository.list_by_version("ki-1", V2)
    assert (flag.kind, flag.existing_item_id) == (DuplicateKind.EXACT, "ki-other")
    assert isinstance(publisher.events[-1], DuplicateDetected)


@pytest.mark.parametrize(
    ("command", "error"),
    [
        (_command(V1_FILE), KnowledgeVersionUnchangedError),
        (_command(change_reason=" "), KnowledgeVersionChangeReasonMissingError),
        (_command(item_id="ki-404"), KnowledgeItemNotFoundError),
        (_command(b"\x89PNG\r\n\x1a\n"), UnsupportedDocumentFormatError),
        (_command(V2_FILE.ljust(MAX_FILE_MB * BYTES_PER_MB + 1)), SourceFileTooLargeError),
    ],
)
def test_nothing_is_stored_or_published_when_the_version_is_refused(
    handler: PublishKnowledgeVersionHandler,
    items: InMemoryKnowledgeItemRepository,
    ingestions: InMemoryKnowledgeIngestionRepository,
    file_store: InMemorySourceFileStore,
    publisher: InMemoryEventPublisher,
    command: PublishKnowledgeVersion,
    error: type[Exception],
):
    with pytest.raises(error):
        handler.publish(command)

    assert len(items.get_by_id("ki-1").versions) == 1
    assert file_store.files == {}
    assert ingestions.ingestions == {}
    assert publisher.events == []


def _survey(text: str) -> ExtractedContent:
    return ExtractedContent(
        document_format=DocumentFormat.DOCX,
        page_count=None,
        blocks=(ContentBlock.paragraph(order=0, text=text, heading_path=("3. Findings",)),),
    )


def _chunk(
    ingestions: InMemoryKnowledgeIngestionRepository,
    items: InMemoryKnowledgeItemRepository,
    contents: InMemoryExtractedContentRepository,
    chunks: InMemoryKnowledgeChunkRepository,
    fingerprints: InMemoryVersionFingerprintRepository,
    version_tag: VersionTag,
) -> None:
    ingestion = KnowledgeIngestion.queue(
        ingestion_id=f"chunk-{version_tag}", item_id="ki-1", version_tag=version_tag, queued_at=NOW
    )
    ingestion.start_extraction(NOW)
    ingestion.wait_for_chunking(NOW)
    ingestions.save(ingestion)
    ChunkKnowledgeContentHandler(
        ingestion_repository=ingestions,
        repository=items,
        extracted_content_repository=contents,
        chunk_repository=chunks,
        fingerprint_repository=fingerprints,
        duplicate_flag_repository=ingestions.flag_repository,
        tokenizer=FakeTokenizer(),
        detector=DETECTOR,
        clock=FakeClock(NOW),
        event_publisher=InMemoryEventPublisher(),
        sizes=ChunkingSizes(target_tokens=400, max_tokens=512, overlap_share=0.12),
        words_per_shingle=12,
    ).chunk(ChunkKnowledgeContent(ingestion_id=ingestion.ingestion_id))


def test_old_chunks_are_superseded_but_kept_when_a_new_version_is_published(
    handler: PublishKnowledgeVersionHandler,
    ingestions: InMemoryKnowledgeIngestionRepository,
    items: InMemoryKnowledgeItemRepository,
    fingerprints: InMemoryVersionFingerprintRepository,
):
    contents = InMemoryExtractedContentRepository()
    chunks = InMemoryKnowledgeChunkRepository(items)
    contents.save("ki-1", V1, _survey(SURVEY_TEXT))
    _chunk(ingestions, items, contents, chunks, fingerprints, V1)
    queries = KnowledgeIngestionQueries(
        ingestion_repository=ingestions,
        repository=items,
        extracted_content_repository=contents,
        chunk_repository=chunks,
        duplicate_flag_repository=ingestions.flag_repository,
        outbox=InMemoryOutbox(ingestions),
        node_directory=FakeNodeDirectory([TEAM.value]),
        queue_monitor=FakeIngestionQueueMonitor(),
    )

    handler.publish(_command())

    old = queries.get_chunks("ki-1", V1)
    assert (old.is_retrievable, len(old.chunks)) == (False, 1)
    assert [chunk.source_reference.version_tag for chunk in chunks.list_active_by_owner(TEAM)] == []


def test_new_version_is_not_flagged_against_its_own_previous_version_when_it_is_chunked(
    handler: PublishKnowledgeVersionHandler,
    ingestions: InMemoryKnowledgeIngestionRepository,
    items: InMemoryKnowledgeItemRepository,
    fingerprints: InMemoryVersionFingerprintRepository,
):
    contents = InMemoryExtractedContentRepository()
    chunks = InMemoryKnowledgeChunkRepository(items)
    contents.save("ki-1", V1, _survey(SURVEY_TEXT))
    _chunk(ingestions, items, contents, chunks, fingerprints, V1)
    handler.publish(_command())
    contents.save("ki-1", V2, _survey(SURVEY_TEXT + " Three more readings were added."))

    _chunk(ingestions, items, contents, chunks, fingerprints, V2)

    assert ingestions.flag_repository.list_by_version("ki-1", V2) == []
    assert [chunk.source_reference.version_tag for chunk in chunks.list_active_by_owner(TEAM)] == [
        V2
    ]
