from datetime import UTC, datetime

import pytest
from tests.fakes.knowledge import (
    FakeClock,
    FakeTokenizer,
    InMemoryDuplicateFlagRepository,
    InMemoryEventPublisher,
    InMemoryExtractedContentRepository,
    InMemoryKnowledgeChunkRepository,
    InMemoryKnowledgeIngestionRepository,
    InMemoryKnowledgeItemRepository,
    InMemoryVersionFingerprintRepository,
)

from offline_rag.knowledge.application.chunk_knowledge_content import (
    ChunkingSizes,
    ChunkKnowledgeContentHandler,
)
from offline_rag.knowledge.application.commands import ChunkKnowledgeContent
from offline_rag.knowledge.application.errors import KnowledgeIngestionNotFoundError
from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.duplicate_detection import (
    DuplicateDetector,
    DuplicateFlag,
    DuplicateKind,
)
from offline_rag.knowledge.domain.events import DuplicateDetected
from offline_rag.knowledge.domain.extracted_content import (
    ContentBlock,
    ContentSource,
    ExtractedContent,
)
from offline_rag.knowledge.domain.knowledge_ingestion import IngestionStatus, KnowledgeIngestion
from offline_rag.knowledge.domain.knowledge_item import KnowledgeItem
from offline_rag.knowledge.domain.knowledge_scope import ConfidentialityLevel, KnowledgeScope
from offline_rag.knowledge.domain.text_fingerprint import normalized_text_hash, reading_text
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.knowledge.infrastructure.errors import KnowledgeStorageError
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
V1 = VersionTag("v1")
TEAM = NodeIdentifier("sp12_inspection_team")
FINDINGS = ("Ultrasonic Wall Thickness Survey", "3. Findings")
COPIED = (
    "Wall loss on riser R-3 is concentrated in the splash zone between EL +5.0 m and EL +9.0 m, "
    "on the south-facing side. The coating there has blistered and disbonded over roughly 1.8 m2, "
    "and cathodic protection does not reach this zone."
)
REPORT = ExtractedContent(
    document_format=DocumentFormat.DOCX,
    page_count=None,
    blocks=(
        ContentBlock.paragraph(order=0, text="Repeat UT survey of riser R-3.", heading_path=()),
        ContentBlock.paragraph(order=1, text=COPIED, heading_path=FINDINGS),
        ContentBlock.table(
            order=2,
            rows=[["Location", "Measured (mm)"], ["EL +8.5 m", "18.9"]],
            heading_path=FINDINGS,
            source=ContentSource.LVM,
            review_reason="OCR read 18.6.",
        ),
    ),
)
SHIFT_REPORT = ExtractedContent(
    document_format=DocumentFormat.DOCX,
    page_count=None,
    blocks=(
        ContentBlock.paragraph(order=0, text="Production at 360 MMscfd.", heading_path=("Plant",)),
        ContentBlock.paragraph(order=1, text=COPIED, heading_path=("Events",)),
        ContentBlock.paragraph(order=2, text="Keep P-4101A isolated.", heading_path=("Actions",)),
    ),
)


@pytest.fixture
def items() -> InMemoryKnowledgeItemRepository:
    return InMemoryKnowledgeItemRepository()


@pytest.fixture
def flags() -> InMemoryDuplicateFlagRepository:
    return InMemoryDuplicateFlagRepository()


@pytest.fixture
def ingestions(
    items: InMemoryKnowledgeItemRepository, flags: InMemoryDuplicateFlagRepository
) -> InMemoryKnowledgeIngestionRepository:
    return InMemoryKnowledgeIngestionRepository(items, flags)


@pytest.fixture
def contents() -> InMemoryExtractedContentRepository:
    return InMemoryExtractedContentRepository()


@pytest.fixture
def chunks(items: InMemoryKnowledgeItemRepository) -> InMemoryKnowledgeChunkRepository:
    return InMemoryKnowledgeChunkRepository(items)


@pytest.fixture
def fingerprints(items: InMemoryKnowledgeItemRepository) -> InMemoryVersionFingerprintRepository:
    return InMemoryVersionFingerprintRepository(items)


@pytest.fixture
def publisher() -> InMemoryEventPublisher:
    return InMemoryEventPublisher()


@pytest.fixture
def handler(
    ingestions: InMemoryKnowledgeIngestionRepository,
    items: InMemoryKnowledgeItemRepository,
    contents: InMemoryExtractedContentRepository,
    chunks: InMemoryKnowledgeChunkRepository,
    fingerprints: InMemoryVersionFingerprintRepository,
    flags: InMemoryDuplicateFlagRepository,
    publisher: InMemoryEventPublisher,
) -> ChunkKnowledgeContentHandler:
    return ChunkKnowledgeContentHandler(
        ingestion_repository=ingestions,
        repository=items,
        extracted_content_repository=contents,
        chunk_repository=chunks,
        fingerprint_repository=fingerprints,
        duplicate_flag_repository=flags,
        tokenizer=FakeTokenizer(),
        detector=DuplicateDetector(
            overlap_chunk_similarity=0.4, ambiguous_from_similarity=0.25, min_chunk_share=0.2
        ),
        clock=FakeClock(NOW),
        event_publisher=publisher,
        sizes=ChunkingSizes(target_tokens=400, max_tokens=512, overlap_share=0.12),
        words_per_shingle=12,
    )


def _add_item(
    items: InMemoryKnowledgeItemRepository,
    contents: InMemoryExtractedContentRepository,
    item_id: str,
    content: ExtractedContent,
    *,
    owner: NodeIdentifier = TEAM,
    metadata: MetadataRecord | None = None,
) -> None:
    items.add(
        KnowledgeItem.submit(
            item_id=item_id,
            owner_node_id=owner,
            scope=KnowledgeScope(confidentiality=ConfidentialityLevel.INTERNAL),
            metadata=metadata or MetadataRecord(document_type="inspection_report"),
            source_file_name=f"{item_id}.docx",
            source_file_reference=f"file-{item_id}",
            document_format=DocumentFormat.DOCX,
            content_hash=f"hash-{item_id}",
            submitted_at=NOW,
        )
    )
    contents.save(item_id, V1, content)


def _waiting(
    ingestions: InMemoryKnowledgeIngestionRepository, item_id: str, ingestion_id: str
) -> None:
    ingestion = KnowledgeIngestion.queue(
        ingestion_id=ingestion_id, item_id=item_id, version_tag=V1, queued_at=NOW
    )
    ingestion.start_extraction(NOW)
    ingestion.wait_for_chunking(NOW)
    ingestions.save(ingestion)


def _chunked(
    handler: ChunkKnowledgeContentHandler,
    ingestions: InMemoryKnowledgeIngestionRepository,
    item_id: str,
) -> KnowledgeIngestion:
    ingestion_id = f"ing-{item_id}"
    _waiting(ingestions, item_id, ingestion_id)
    return handler.chunk(ChunkKnowledgeContent(ingestion_id=ingestion_id))


@pytest.fixture
def report_id(
    items: InMemoryKnowledgeItemRepository, contents: InMemoryExtractedContentRepository
) -> str:
    _add_item(items, contents, "ki-report", REPORT)
    return "ki-report"


def test_chunks_are_stored_and_run_completes_with_counts_when_version_is_chunked(
    handler: ChunkKnowledgeContentHandler,
    ingestions: InMemoryKnowledgeIngestionRepository,
    chunks: InMemoryKnowledgeChunkRepository,
    report_id: str,
):
    result = _chunked(handler, ingestions, report_id)

    stored = chunks.list_by_version(report_id, V1)
    assert [chunk.source_reference.heading_path for chunk in stored] == [(), FINDINGS]
    assert (result.status, result.chunk_count, result.blocks_for_review, result.attempts) == (
        IngestionStatus.COMPLETED,
        2,
        1,
        2,
    )
    assert ingestions.get_by_id(f"ing-{report_id}").status == IngestionStatus.COMPLETED


def test_chunks_carry_the_version_metadata_when_version_is_chunked(
    handler: ChunkKnowledgeContentHandler,
    ingestions: InMemoryKnowledgeIngestionRepository,
    chunks: InMemoryKnowledgeChunkRepository,
    report_id: str,
):
    _chunked(handler, ingestions, report_id)

    assert {chunk.metadata.document_type for chunk in chunks.list_by_version(report_id, V1)} == {
        "inspection_report"
    }


def test_text_hash_of_the_version_is_stored_when_version_is_chunked(
    handler: ChunkKnowledgeContentHandler,
    ingestions: InMemoryKnowledgeIngestionRepository,
    fingerprints: InMemoryVersionFingerprintRepository,
    report_id: str,
):
    _chunked(handler, ingestions, report_id)

    assert fingerprints.text_hashes[(report_id, V1)] == normalized_text_hash(reading_text(REPORT))


def test_no_flag_is_raised_when_no_other_item_repeats_the_text(
    handler: ChunkKnowledgeContentHandler,
    ingestions: InMemoryKnowledgeIngestionRepository,
    flags: InMemoryDuplicateFlagRepository,
    publisher: InMemoryEventPublisher,
    items: InMemoryKnowledgeItemRepository,
    contents: InMemoryExtractedContentRepository,
    report_id: str,
):
    _chunked(handler, ingestions, report_id)
    unrelated = ExtractedContent(
        document_format=DocumentFormat.DOCX,
        page_count=None,
        blocks=(
            ContentBlock.paragraph(order=0, text="Firewater caisson inspection, no findings."),
        ),
    )
    _add_item(items, contents, "ki-caisson", unrelated)

    _chunked(handler, ingestions, "ki-caisson")

    assert flags.list_by_version("ki-caisson", V1) == []
    assert publisher.events == []


def test_near_duplicate_is_flagged_and_published_when_another_item_has_the_same_text(
    handler: ChunkKnowledgeContentHandler,
    ingestions: InMemoryKnowledgeIngestionRepository,
    flags: InMemoryDuplicateFlagRepository,
    publisher: InMemoryEventPublisher,
    items: InMemoryKnowledgeItemRepository,
    contents: InMemoryExtractedContentRepository,
    report_id: str,
):
    _chunked(handler, ingestions, report_id)
    _add_item(items, contents, "ki-copy", REPORT)

    _chunked(handler, ingestions, "ki-copy")

    expected = DuplicateFlag(
        item_id="ki-copy",
        version_tag=V1,
        kind=DuplicateKind.NEAR,
        existing_item_id=report_id,
        existing_version_tag=V1,
        score=1.0,
    )
    assert flags.list_by_version("ki-copy", V1) == [expected]
    assert publisher.events == [
        DuplicateDetected(
            occurred_at=NOW,
            item_id="ki-copy",
            version_tag=V1,
            kind=DuplicateKind.NEAR,
            existing_item_id=report_id,
            existing_version_tag=V1,
            score=1.0,
            is_ambiguous=False,
        )
    ]


def test_metadata_variant_is_flagged_when_the_same_text_has_other_metadata(
    handler: ChunkKnowledgeContentHandler,
    ingestions: InMemoryKnowledgeIngestionRepository,
    flags: InMemoryDuplicateFlagRepository,
    items: InMemoryKnowledgeItemRepository,
    contents: InMemoryExtractedContentRepository,
    report_id: str,
):
    _chunked(handler, ingestions, report_id)
    _add_item(
        items, contents, "ki-copy", REPORT, metadata=MetadataRecord(document_type="project_report")
    )

    _chunked(handler, ingestions, "ki-copy")

    assert [flag.kind for flag in flags.list_by_version("ki-copy", V1)] == [
        DuplicateKind.METADATA_VARIANT
    ]


def test_overlap_is_flagged_when_a_paragraph_of_another_item_is_copied(
    handler: ChunkKnowledgeContentHandler,
    ingestions: InMemoryKnowledgeIngestionRepository,
    flags: InMemoryDuplicateFlagRepository,
    items: InMemoryKnowledgeItemRepository,
    contents: InMemoryExtractedContentRepository,
    report_id: str,
):
    _chunked(handler, ingestions, report_id)
    _add_item(items, contents, "ki-shift", SHIFT_REPORT)

    _chunked(handler, ingestions, "ki-shift")

    (flag,) = flags.list_by_version("ki-shift", V1)
    assert (flag.kind, flag.existing_item_id, flag.is_ambiguous) == (
        DuplicateKind.OVERLAP,
        report_id,
        False,
    )
    assert flag.score == pytest.approx(1 / 3)


def test_no_flag_is_raised_when_the_copy_belongs_to_another_node(
    handler: ChunkKnowledgeContentHandler,
    ingestions: InMemoryKnowledgeIngestionRepository,
    flags: InMemoryDuplicateFlagRepository,
    items: InMemoryKnowledgeItemRepository,
    contents: InMemoryExtractedContentRepository,
    report_id: str,
):
    _chunked(handler, ingestions, report_id)
    _add_item(items, contents, "ki-copy", REPORT, owner=NodeIdentifier("platform_sp12"))

    _chunked(handler, ingestions, "ki-copy")

    assert flags.list_by_version("ki-copy", V1) == []


def test_message_seen_again_changes_nothing_when_run_has_completed(
    handler: ChunkKnowledgeContentHandler,
    ingestions: InMemoryKnowledgeIngestionRepository,
    report_id: str,
):
    _chunked(handler, ingestions, report_id)

    again = handler.chunk(ChunkKnowledgeContent(ingestion_id=f"ing-{report_id}"))

    assert (again.status, again.attempts) == (IngestionStatus.COMPLETED, 2)


def test_chunks_and_flags_are_replaced_and_no_event_repeats_when_a_version_is_chunked_again(
    handler: ChunkKnowledgeContentHandler,
    ingestions: InMemoryKnowledgeIngestionRepository,
    chunks: InMemoryKnowledgeChunkRepository,
    flags: InMemoryDuplicateFlagRepository,
    publisher: InMemoryEventPublisher,
    items: InMemoryKnowledgeItemRepository,
    contents: InMemoryExtractedContentRepository,
    report_id: str,
):
    _chunked(handler, ingestions, report_id)
    _add_item(items, contents, "ki-copy", REPORT)
    _chunked(handler, ingestions, "ki-copy")
    stored_chunks = chunks.list_by_version("ki-copy", V1)
    stored_flags = flags.list_by_version("ki-copy", V1)
    publisher.events.clear()
    _waiting(ingestions, "ki-copy", "ing-again")

    handler.chunk(ChunkKnowledgeContent(ingestion_id="ing-again"))

    assert chunks.list_by_version("ki-copy", V1) == stored_chunks
    assert flags.list_by_version("ki-copy", V1) == stored_flags
    assert publisher.events == []


def test_run_fails_when_the_version_has_no_extracted_content(
    handler: ChunkKnowledgeContentHandler,
    ingestions: InMemoryKnowledgeIngestionRepository,
    contents: InMemoryExtractedContentRepository,
    report_id: str,
):
    contents.contents.clear()

    result = _chunked(handler, ingestions, report_id)

    assert (result.status, result.failure_code) == (
        IngestionStatus.FAILED,
        "KNOWLEDGE_EXTRACTED_CONTENT_NOT_FOUND",
    )


def test_error_is_raised_for_a_retry_and_run_stays_chunking_when_the_database_fails(
    ingestions: InMemoryKnowledgeIngestionRepository,
    items: InMemoryKnowledgeItemRepository,
    contents: InMemoryExtractedContentRepository,
    fingerprints: InMemoryVersionFingerprintRepository,
    flags: InMemoryDuplicateFlagRepository,
    publisher: InMemoryEventPublisher,
    report_id: str,
):
    class FailingChunks(InMemoryKnowledgeChunkRepository):
        def replace(self, *args: object) -> None:
            operation = "replace_chunks"
            raise KnowledgeStorageError(operation)

    handler = ChunkKnowledgeContentHandler(
        ingestion_repository=ingestions,
        repository=items,
        extracted_content_repository=contents,
        chunk_repository=FailingChunks(items),
        fingerprint_repository=fingerprints,
        duplicate_flag_repository=flags,
        tokenizer=FakeTokenizer(),
        detector=DuplicateDetector(
            overlap_chunk_similarity=0.4, ambiguous_from_similarity=0.25, min_chunk_share=0.2
        ),
        clock=FakeClock(NOW),
        event_publisher=publisher,
        sizes=ChunkingSizes(target_tokens=400, max_tokens=512, overlap_share=0.12),
        words_per_shingle=12,
    )
    _waiting(ingestions, report_id, "ing-1")

    with pytest.raises(KnowledgeStorageError):
        handler.chunk(ChunkKnowledgeContent(ingestion_id="ing-1"))

    assert ingestions.get_by_id("ing-1").status == IngestionStatus.CHUNKING


def test_nothing_is_chunked_when_run_is_not_waiting_for_chunking(
    handler: ChunkKnowledgeContentHandler,
    ingestions: InMemoryKnowledgeIngestionRepository,
    chunks: InMemoryKnowledgeChunkRepository,
    report_id: str,
):
    ingestions.save(
        KnowledgeIngestion.queue(
            ingestion_id="ing-1", item_id=report_id, version_tag=V1, queued_at=NOW
        )
    )

    result = handler.chunk(ChunkKnowledgeContent(ingestion_id="ing-1"))

    assert result.status == IngestionStatus.QUEUED
    assert chunks.list_by_version(report_id, V1) == []


def test_lookup_raises_not_found_when_ingestion_does_not_exist(
    handler: ChunkKnowledgeContentHandler,
):
    with pytest.raises(KnowledgeIngestionNotFoundError):
        handler.chunk(ChunkKnowledgeContent(ingestion_id="ing-404"))
