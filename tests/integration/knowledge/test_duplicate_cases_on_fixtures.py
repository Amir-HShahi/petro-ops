"""The duplicate cases of `fixtures/docs/README.md`, through the real parser (ADR 0010).

Storage is in memory; the parser, the chunker and the detector are the real ones,
with the thresholds of `Settings`.
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from tests.fakes.knowledge import (
    FakeClock,
    FakeIdGenerator,
    FakeNodeDirectory,
    InMemoryEventPublisher,
    InMemoryExtractedContentRepository,
    InMemoryKnowledgeChunkRepository,
    InMemoryKnowledgeIngestionRepository,
    InMemoryKnowledgeItemRepository,
    InMemorySourceFileStore,
    InMemoryVersionFingerprintRepository,
)

from offline_rag.knowledge.application.chunk_knowledge_content import (
    ChunkingSizes,
    ChunkKnowledgeContentHandler,
)
from offline_rag.knowledge.application.commands import (
    ChunkKnowledgeContent,
    ExtractKnowledgeContent,
    PublishKnowledgeVersion,
    SubmitKnowledgeItem,
)
from offline_rag.knowledge.application.extract_knowledge_content import (
    ExtractKnowledgeContentHandler,
)
from offline_rag.knowledge.application.ingestion_queueing import IngestionReceipt
from offline_rag.knowledge.application.publish_knowledge_version import (
    PublishKnowledgeVersionHandler,
)
from offline_rag.knowledge.application.submit_knowledge_item import SubmitKnowledgeItemHandler
from offline_rag.knowledge.domain.duplicate_detection import (
    DuplicateDetector,
    DuplicateFlag,
    DuplicateKind,
)
from offline_rag.knowledge.domain.knowledge_ingestion import IngestionStatus
from offline_rag.knowledge.domain.knowledge_scope import ConfidentialityLevel, KnowledgeScope
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.knowledge.infrastructure.approximate_tokenizer import ApproximateTokenizer
from offline_rag.knowledge.infrastructure.docling_document_parser import DoclingDocumentParser
from offline_rag.knowledge.infrastructure.libreoffice_doc_converter import (
    LibreOfficeDocConverter,
)
from offline_rag.settings import Settings
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not Settings().docling_models_dir.is_dir(), reason="Docling models are not downloaded"
    ),
]

DOCS = Path(__file__).parents[3] / "fixtures" / "docs"
V1, V2 = VersionTag("v1"), VersionTag("v2")
# Same-Node scope (ADR 0010): every case is submitted for one Node, even where
# the manifest gives the shift report to platform_sp12.
TEAM = NodeIdentifier("sp12_inspection_team")
SETTINGS = Settings()

Ingest = Callable[[str], IngestionReceipt]


class Pipeline:
    """Submit, extract and chunk one fixture after another, as the workers would."""

    def __init__(self, parser: DoclingDocumentParser) -> None:
        self.items = InMemoryKnowledgeItemRepository()
        self.ingestions = InMemoryKnowledgeIngestionRepository(self.items)
        self.chunks = InMemoryKnowledgeChunkRepository(self.items)
        files = InMemorySourceFileStore()
        contents = InMemoryExtractedContentRepository()
        fingerprints = InMemoryVersionFingerprintRepository(self.items)
        clock, ids, events = FakeClock(), FakeIdGenerator(), InMemoryEventPublisher()
        detector = DuplicateDetector(
            overlap_chunk_similarity=SETTINGS.overlap_chunk_similarity,
            ambiguous_from_similarity=SETTINGS.overlap_ambiguous_from_similarity,
            min_chunk_share=SETTINGS.overlap_min_chunk_share,
        )
        self.submit_handler = SubmitKnowledgeItemHandler(
            ingestion_repository=self.ingestions,
            node_directory=FakeNodeDirectory([TEAM.value]),
            source_file_store=files,
            fingerprint_repository=fingerprints,
            detector=detector,
            clock=clock,
            id_generator=ids,
            event_publisher=events,
            max_file_mb=SETTINGS.max_file_mb,
        )
        self.publish_handler = PublishKnowledgeVersionHandler(
            ingestion_repository=self.ingestions,
            repository=self.items,
            source_file_store=files,
            fingerprint_repository=fingerprints,
            detector=detector,
            clock=clock,
            id_generator=ids,
            event_publisher=events,
            max_file_mb=SETTINGS.max_file_mb,
        )
        self.extract_handler = ExtractKnowledgeContentHandler(
            ingestion_repository=self.ingestions,
            repository=self.items,
            source_file_store=files,
            parser=parser,
            extracted_content_repository=contents,
            clock=clock,
            id_generator=ids,
            event_publisher=events,
            min_page_text_chars=SETTINGS.min_page_text_chars,
        )
        self.chunk_handler = ChunkKnowledgeContentHandler(
            ingestion_repository=self.ingestions,
            repository=self.items,
            extracted_content_repository=contents,
            chunk_repository=self.chunks,
            fingerprint_repository=fingerprints,
            duplicate_flag_repository=self.ingestions.flag_repository,
            tokenizer=ApproximateTokenizer(),
            detector=detector,
            clock=clock,
            event_publisher=events,
            sizes=ChunkingSizes(
                target_tokens=SETTINGS.chunk_target_tokens,
                max_tokens=SETTINGS.chunk_max_tokens,
                overlap_share=SETTINGS.chunk_overlap_share,
            ),
            words_per_shingle=SETTINGS.duplicate_shingle_words,
        )

    def ingest(self, relative_path: str) -> IngestionReceipt:
        path = DOCS / relative_path
        receipt = self.submit_handler.submit(
            SubmitKnowledgeItem(
                owner_node_id=TEAM,
                source_file_name=path.name,
                content=path.read_bytes(),
                scope=KnowledgeScope(confidentiality=ConfidentialityLevel.INTERNAL),
                metadata=MetadataRecord(document_type="inspection_report"),
            )
        )
        self.run_steps(receipt.ingestion_id)
        return receipt

    def publish(self, item_id: str, relative_path: str) -> IngestionReceipt:
        path = DOCS / relative_path
        receipt = self.publish_handler.publish(
            PublishKnowledgeVersion(
                item_id=item_id,
                source_file_name=path.name,
                content=path.read_bytes(),
                change_reason="Adds 3 readings and a change note.",
            )
        )
        self.run_steps(receipt.ingestion_id)
        return receipt

    def run_steps(self, ingestion_id: str) -> None:
        self.extract_handler.extract(ExtractKnowledgeContent(ingestion_id=ingestion_id))
        self.chunk_handler.chunk(ChunkKnowledgeContent(ingestion_id=ingestion_id))
        assert self.ingestions.get_by_id(ingestion_id).status == IngestionStatus.COMPLETED

    def flags(self, receipt: IngestionReceipt) -> list[DuplicateFlag]:
        return self.ingestions.flag_repository.list_by_version(receipt.item_id, receipt.version_tag)


@pytest.fixture(scope="module")
def parser() -> DoclingDocumentParser:
    """One parser for the module, so the PDF models load once."""
    return DoclingDocumentParser(
        models_dir=SETTINGS.docling_models_dir,
        doc_converter=LibreOfficeDocConverter(soffice_path="soffice", timeout_s=120),
    )


@pytest.fixture
def pipeline(parser: DoclingDocumentParser) -> Pipeline:
    return Pipeline(parser)


def test_byte_identical_cv_is_flagged_as_exact_duplicate_when_both_are_ingested(
    pipeline: Pipeline,
):
    profile = pipeline.ingest("synthetic/profile_leila_moradi.docx")

    copy = pipeline.ingest("cases/cv_moradi_final.docx")

    (flag,) = pipeline.flags(copy)
    assert (flag.kind, flag.existing_item_id, flag.score) == (
        DuplicateKind.EXACT,
        profile.item_id,
        1.0,
    )
    assert copy.item_id in pipeline.items.items


@pytest.mark.slow
def test_pdf_of_the_same_report_overlaps_all_its_chunks_when_both_are_ingested(
    pipeline: Pipeline,
):
    docx = pipeline.ingest("synthetic/inspection_sp12_riser_r3_2024.docx")

    pdf = pipeline.ingest("cases/inspection_sp12_riser_r3_2024.pdf")

    # The PDF names its document ID INS-01-PDF, so its text is not identical
    # and it is not a near duplicate; every chunk repeats the DOCX, though.
    (flag,) = pipeline.flags(pdf)
    assert (flag.kind, flag.existing_item_id, flag.score, flag.is_ambiguous) == (
        DuplicateKind.OVERLAP,
        docx.item_id,
        1.0,
        False,
    )


def test_shift_report_overlaps_the_survey_when_it_repeats_the_findings_paragraph(
    pipeline: Pipeline,
):
    survey = pipeline.ingest("synthetic/inspection_sp12_riser_r3_2026_v1.docx")

    shift = pipeline.ingest("cases/shift_report_sp12_2026_09_27.docx")

    (flag,) = pipeline.flags(shift)
    assert (flag.kind, flag.existing_item_id, flag.is_ambiguous) == (
        DuplicateKind.OVERLAP,
        survey.item_id,
        False,
    )


def test_surveys_of_two_years_are_not_flagged_when_they_only_share_the_template(
    pipeline: Pipeline,
):
    pipeline.ingest("synthetic/inspection_sp12_riser_r3_2024.docx")

    later = pipeline.ingest("synthetic/inspection_sp12_riser_r3_2026_v1.docx")

    assert pipeline.flags(later) == []


def test_second_version_supersedes_the_first_and_is_not_flagged_when_published(
    pipeline: Pipeline,
):
    first = pipeline.ingest("synthetic/inspection_sp12_riser_r3_2026_v1.docx")

    second = pipeline.publish(first.item_id, "cases/inspection_sp12_riser_r3_2026_v2.docx")

    active = pipeline.chunks.list_active_by_owner(TEAM)
    assert second.version_tag == V2
    assert pipeline.flags(second) == []
    assert {chunk.source_reference.version_tag for chunk in active} == {V2}
    assert pipeline.chunks.list_by_version(first.item_id, V1)


def test_no_chunk_passes_the_hard_limit_when_fixtures_are_chunked(pipeline: Pipeline):
    for path in (
        "synthetic/inspection_sp12_riser_r3_2026_v1.docx",
        "synthetic/profile_leila_moradi.docx",
        "cases/shift_report_sp12_2026_09_27.docx",
    ):
        pipeline.ingest(path)

    chunks = pipeline.chunks.list_active_by_owner(TEAM)

    assert chunks
    assert max(chunk.token_count for chunk in chunks) <= SETTINGS.chunk_max_tokens
