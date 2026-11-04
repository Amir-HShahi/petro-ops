from datetime import UTC, datetime

import pytest
from structlog.testing import capture_logs
from tests.fakes.knowledge import (
    FakeClock,
    FakeLvm,
    FakePageRenderer,
    FakeTableOcr,
    InMemoryEventPublisher,
    InMemoryExtractedContentRepository,
    InMemoryKnowledgeItemRepository,
    InMemorySourceFileStore,
)

from offline_rag.knowledge.application.commands import ReadPagesWithLvm
from offline_rag.knowledge.application.errors import ExtractedContentNotFoundError
from offline_rag.knowledge.application.ports import PageReading, PageTable
from offline_rag.knowledge.application.read_pages_with_lvm import ReadPagesWithLvmHandler
from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.events import KnowledgeContentExtracted, PagesReadWithLvm
from offline_rag.knowledge.domain.extracted_content import (
    ContentBlock,
    ContentBlockKind,
    ContentSource,
    ExtractedContent,
)
from offline_rag.knowledge.domain.knowledge_item import KnowledgeItem
from offline_rag.knowledge.domain.knowledge_scope import ConfidentialityLevel, KnowledgeScope
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.knowledge.infrastructure.errors import ModelUnavailableError
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
V1 = VersionTag("v1")
READINGS_TABLE = PageTable(
    header=("Location", "Measured (mm)"),
    rows=(("R-3 EL +8.5 m, 6 o'clock", "21.0"),),
    row_labels=("R-3 EL +8.5 m, 6 o'clock",),
)
SCANNED_PAGE = PageReading(
    items=("Coating in good condition apart from light rust staining.", READINGS_TABLE),
)
MATCHING_OCR = [[["Location", "Measured (mm)"], ["R-3 EL +8.5 m, 6 o'clock", "21.0"]]]


class Pipeline:
    """The handler with all its fakes, built for one test."""

    def __init__(
        self,
        *,
        document_format: DocumentFormat = DocumentFormat.PDF,
        lvm: FakeLvm | None = None,
        table_ocr: FakeTableOcr | None = None,
    ) -> None:
        self.repository = InMemoryKnowledgeItemRepository()
        self.file_store = InMemorySourceFileStore()
        self.contents = InMemoryExtractedContentRepository()
        self.renderer = FakePageRenderer()
        self.table_ocr = table_ocr or FakeTableOcr({2: MATCHING_OCR})
        self.publisher = InMemoryEventPublisher()
        self.handler = ReadPagesWithLvmHandler(
            repository=self.repository,
            source_file_store=self.file_store,
            extracted_content_repository=self.contents,
            page_renderer=self.renderer,
            lvm=lvm or FakeLvm({2: SCANNED_PAGE}),
            table_ocr=self.table_ocr,
            clock=FakeClock(NOW),
            event_publisher=self.publisher,
            min_page_text_chars=20,
        )
        reference = self.file_store.save("baseline.pdf", b"%PDF-1.7")
        self.repository.add(
            KnowledgeItem.submit(
                item_id="ki-1",
                owner_node_id=NodeIdentifier("sp12_inspection_team"),
                scope=KnowledgeScope(confidentiality=ConfidentialityLevel.INTERNAL),
                metadata=MetadataRecord(),
                source_file_name="baseline.pdf",
                source_file_reference=reference,
                document_format=document_format,
                content_hash="hash",
                submitted_at=NOW,
            )
        )
        if document_format == DocumentFormat.PDF:
            self.contents.save(
                "ki-1",
                V1,
                ExtractedContent(
                    document_format=DocumentFormat.PDF,
                    page_count=2,
                    blocks=(
                        ContentBlock.paragraph(
                            order=0, text="Page one has a full text layer.", page_number=1
                        ),
                    ),
                ),
            )
        else:
            self.contents.save(
                "ki-1",
                V1,
                ExtractedContent(document_format=document_format, page_count=None, blocks=()),
            )

    def read(self, page_numbers: tuple[int, ...] | None = None) -> ExtractedContent:
        return self.handler.read(
            ReadPagesWithLvm(item_id="ki-1", version_tag=V1, page_numbers=page_numbers)
        )


def test_only_pages_without_text_are_read_when_no_pages_are_given():
    pipeline = Pipeline()

    pipeline.read()

    assert pipeline.renderer.pages == [2]


def test_lvm_blocks_are_stored_on_their_page_when_page_is_read():
    pipeline = Pipeline()

    content = pipeline.read()

    page_two = [block for block in content.blocks if block.page_number == 2]
    assert [block.kind for block in page_two] == [ContentBlockKind.TEXT, ContentBlockKind.TABLE]
    assert {block.source for block in page_two} == {ContentSource.LVM}
    assert page_two[1].text == "Location | Measured (mm)\nR-3 EL +8.5 m, 6 o'clock | 21.0"
    assert pipeline.contents.get("ki-1", V1) == content


def test_text_layer_blocks_stay_when_other_pages_are_read():
    content = Pipeline().read()

    assert content.blocks[0].text == "Page one has a full text layer."
    assert content.blocks[0].source == ContentSource.TEXT_LAYER


def test_table_is_trusted_when_ocr_reads_the_same_cells():
    content = Pipeline().read()

    table = next(block for block in content.blocks if block.kind == ContentBlockKind.TABLE)
    assert not table.needs_human_review


def test_table_is_marked_for_review_when_ocr_reads_a_different_value():
    ocr = FakeTableOcr({2: [[["Location", "Measured (mm)"], ["R-3 EL +8.5 m, 6 o'clock", "20.0"]]]})
    pipeline = Pipeline(table_ocr=ocr)

    content = pipeline.read()

    table = next(block for block in content.blocks if block.kind == ContentBlockKind.TABLE)
    assert table.needs_human_review
    assert table.review_reason == "Row 2, column 2 differs: LVM read '21.0', OCR read '20.0'."
    assert pipeline.publisher.events == [
        PagesReadWithLvm(
            occurred_at=NOW, item_id="ki-1", version_tag=V1, page_numbers=(2,), tables_for_review=1
        )
    ]


def test_ocr_is_skipped_when_the_page_has_no_tables():
    ocr = FakeTableOcr()
    lvm = FakeLvm({2: PageReading(items=("Only running text on this scanned page.",))})
    pipeline = Pipeline(lvm=lvm, table_ocr=ocr)

    pipeline.read()

    assert ocr.pages == []


def test_given_pages_are_read_even_when_they_have_a_text_layer():
    pipeline = Pipeline()

    pipeline.read(page_numbers=(1, 2))

    assert pipeline.renderer.pages == [1, 2]


@pytest.mark.parametrize("document_format", [DocumentFormat.DOCX, DocumentFormat.DOC])
def test_nothing_is_read_when_the_file_has_no_pages(document_format: DocumentFormat):
    pipeline = Pipeline(document_format=document_format)

    pipeline.read()

    assert pipeline.renderer.pages == []
    assert pipeline.publisher.events == []


def test_error_is_raised_when_the_version_was_not_extracted():
    pipeline = Pipeline()
    pipeline.contents.contents.clear()

    with pytest.raises(ExtractedContentNotFoundError):
        pipeline.read()


def _extracted_event(pages_without_text: tuple[int, ...]) -> KnowledgeContentExtracted:
    return KnowledgeContentExtracted(
        occurred_at=NOW,
        item_id="ki-1",
        version_tag=V1,
        block_count=1,
        pages_without_text=pages_without_text,
    )


def test_pages_are_read_when_extraction_reports_pages_without_text():
    pipeline = Pipeline()

    pipeline.handler.on_knowledge_content_extracted(_extracted_event((2,)))

    assert pipeline.renderer.pages == [2]


def test_nothing_is_read_when_extraction_reports_no_pages_without_text():
    pipeline = Pipeline()

    pipeline.handler.on_knowledge_content_extracted(_extracted_event(()))

    assert pipeline.renderer.pages == []


def test_failure_is_logged_and_extraction_stays_when_the_model_server_is_off():
    pipeline = Pipeline(lvm=FakeLvm(error=ModelUnavailableError("gemma4:12b-it-qat")))
    before = pipeline.contents.get("ki-1", V1)

    with capture_logs() as logs:
        pipeline.handler.on_knowledge_content_extracted(_extracted_event((2,)))

    assert pipeline.contents.get("ki-1", V1) == before
    assert logs == [
        {
            "event": "pages_read_with_lvm_failed",
            "log_level": "warning",
            "item_id": "ki-1",
            "version_tag": "v1",
            "page_numbers": [2],
            "code": "KNOWLEDGE_MODEL_UNAVAILABLE",
        }
    ]


def test_one_model_is_loaded_at_a_time_when_several_pages_are_read():
    calls: list[str] = []
    lvm = FakeLvm({1: SCANNED_PAGE, 2: SCANNED_PAGE}, calls=calls)
    ocr = FakeTableOcr({1: MATCHING_OCR, 2: MATCHING_OCR}, calls=calls)
    pipeline = Pipeline(lvm=lvm, table_ocr=ocr)

    pipeline.read(page_numbers=(1, 2))

    assert calls == [
        "lvm reads page 1",
        "lvm reads page 2",
        "lvm released",
        "ocr reads page 1",
        "ocr reads page 2",
        "ocr released",
    ]


def test_ocr_model_is_never_loaded_when_no_page_has_tables():
    calls: list[str] = []
    lvm = FakeLvm({2: PageReading(items=("Running text only.",))}, calls=calls)
    pipeline = Pipeline(lvm=lvm, table_ocr=FakeTableOcr(calls=calls))

    pipeline.read()

    assert calls == ["lvm reads page 2", "lvm released"]


def test_lvm_is_released_when_reading_a_page_fails():
    calls: list[str] = []
    lvm = FakeLvm(error=ModelUnavailableError("gemma4:12b-it-qat"), calls=calls)
    pipeline = Pipeline(lvm=lvm, table_ocr=FakeTableOcr(calls=calls))

    with pytest.raises(ModelUnavailableError):
        pipeline.read()

    assert calls == ["lvm reads page 2", "lvm released"]


def test_blocks_keep_the_order_of_the_page_when_a_table_comes_between_paragraphs():
    reading = PageReading(items=("Baseline readings", READINGS_TABLE, "Coating in good condition."))
    pipeline = Pipeline(lvm=FakeLvm({2: reading}))

    content = pipeline.read()

    page_two = [block for block in content.blocks if block.page_number == 2]
    assert [block.kind for block in page_two] == [
        ContentBlockKind.TEXT,
        ContentBlockKind.TABLE,
        ContentBlockKind.TEXT,
    ]
    assert page_two[2].text == "Coating in good condition."
