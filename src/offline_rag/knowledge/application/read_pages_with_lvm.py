"""Use case: read PDF pages without a text layer with the local vision model (ADR 0002)."""

from collections.abc import Sequence

import structlog

from offline_rag.knowledge.application.commands import ReadPagesWithLvm
from offline_rag.knowledge.application.ports import (
    LVM,
    Clock,
    EventPublisher,
    ExtractedContentRepository,
    KnowledgeIngestionRepository,
    KnowledgeItemRepository,
    PageReading,
    PageRenderer,
    SourceFileStore,
    TableOcr,
)
from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.events import PagesReadWithLvm
from offline_rag.knowledge.domain.extracted_content import (
    ContentBlock,
    ContentSource,
    ExtractedContent,
)
from offline_rag.knowledge.domain.knowledge_ingestion import IngestionStatus, KnowledgeIngestion
from offline_rag.knowledge.domain.scanned_table_check import find_table_review_reason
from offline_rag.shared_kernel.errors import InfrastructureError, ProjectError

log = structlog.get_logger()


class ReadPagesWithLvmHandler:
    """Renders the pages, has the LVM read them and checks every table with the OCR model.

    The vision worker runs it for ingestions waiting for page reading (ADR 0005).
    The blocks it writes are marked as LVM text. A table the two models disagree on
    is kept, but marked for human review, so a wrong reading is never silent.
    """

    def __init__(
        self,
        *,
        ingestion_repository: KnowledgeIngestionRepository,
        repository: KnowledgeItemRepository,
        source_file_store: SourceFileStore,
        extracted_content_repository: ExtractedContentRepository,
        page_renderer: PageRenderer,
        lvm: LVM,
        table_ocr: TableOcr,
        clock: Clock,
        event_publisher: EventPublisher,
        min_page_text_chars: int,
    ) -> None:
        """Create the handler.

        Args:
            ingestion_repository: Where KnowledgeIngestions are stored.
            repository: Where KnowledgeItems are stored.
            source_file_store: Where the original files are kept.
            extracted_content_repository: Where the extracted blocks are kept.
            page_renderer: Draws a PDF page as an image.
            lvm: Reads text and tables from a page image.
            table_ocr: Reads tables a second time, to check the LVM.
            clock: Stamps the ingestion and the event.
            event_publisher: Receives `PagesReadWithLvm`.
            min_page_text_chars: Below this many characters a page has no text layer.
        """
        self._ingestion_repository = ingestion_repository
        self._repository = repository
        self._source_file_store = source_file_store
        self._extracted_content_repository = extracted_content_repository
        self._page_renderer = page_renderer
        self._lvm = lvm
        self._table_ocr = table_ocr
        self._clock = clock
        self._event_publisher = event_publisher
        self._min_page_text_chars = min_page_text_chars

    def read(self, command: ReadPagesWithLvm) -> KnowledgeIngestion:
        """Read the pages without a text layer, store their blocks and complete the ingestion.

        The new blocks replace those stored for the same pages, so a message seen
        again is safe. An error that a retry cannot fix ends the ingestion as FAILED.

        Raises:
            KnowledgeIngestionNotFoundError: The ingestion does not exist.
            InfrastructureError: A model, store or the database failed; the step
                can be retried.
        """
        ingestion = self._ingestion_repository.get_by_id(command.ingestion_id)
        if ingestion.status != IngestionStatus.READING_PAGES:
            log.info(
                "pages_read_with_lvm_skipped",
                ingestion_id=ingestion.ingestion_id,
                status=ingestion.status.value,
            )
            return ingestion

        ingestion.start_page_reading(self._clock.now())
        self._ingestion_repository.save(ingestion)
        try:
            content, page_numbers, tables_for_review = self._read_pages(
                ingestion, command.page_numbers
            )
        except InfrastructureError:
            raise
        except ProjectError as error:
            ingestion.fail(
                failure_code=error.code, failure_detail=str(error), now=self._clock.now()
            )
            self._ingestion_repository.save(ingestion)
            log.warning(
                "pages_read_with_lvm_failed",
                ingestion_id=ingestion.ingestion_id,
                item_id=ingestion.item_id,
                code=error.code,
            )
            return ingestion

        ingestion.complete(
            blocks_for_review=sum(block.needs_human_review for block in content.blocks),
            now=self._clock.now(),
        )
        self._ingestion_repository.save(ingestion)
        if not page_numbers:
            return ingestion
        self._event_publisher.publish(
            [
                PagesReadWithLvm(
                    occurred_at=self._clock.now(),
                    item_id=ingestion.item_id,
                    version_tag=ingestion.version_tag,
                    page_numbers=page_numbers,
                    tables_for_review=tables_for_review,
                )
            ]
        )
        log.info(
            "pages_read_with_lvm",
            ingestion_id=ingestion.ingestion_id,
            item_id=ingestion.item_id,
            version_tag=ingestion.version_tag.value,
            page_numbers=list(page_numbers),
            tables_for_review=tables_for_review,
        )
        return ingestion

    def _read_pages(
        self, ingestion: KnowledgeIngestion, requested_pages: tuple[int, ...] | None
    ) -> tuple[ExtractedContent, tuple[int, ...], int]:
        item = self._repository.get_by_id(ingestion.item_id)
        version = item.get_version(ingestion.version_tag)
        content = self._extracted_content_repository.get(item.item_id, version.version_tag)
        page_numbers = requested_pages or content.pages_without_text(
            min_page_text_chars=self._min_page_text_chars
        )
        if version.document_format != DocumentFormat.PDF or not page_numbers:
            return content, (), 0

        pdf = self._source_file_store.read(version.source_file_reference)
        page_blocks = self._read_in_two_passes(pdf, page_numbers)
        content = content.with_page_blocks(page_blocks)
        self._extracted_content_repository.save(item.item_id, version.version_tag, content)
        tables_for_review = sum(
            block.needs_human_review for blocks in page_blocks.values() for block in blocks
        )
        return content, tuple(page_numbers), tables_for_review

    def _read_in_two_passes(
        self, pdf: bytes, page_numbers: Sequence[int]
    ) -> dict[int, list[ContentBlock]]:
        # Both models together need about 11 GB, which overloads a 16 GB machine, so
        # the LVM reads every page first and the OCR model then reads the tables,
        # each released when its pass ends (ADR 0002).
        images = {page: self._page_renderer.render(pdf, page) for page in page_numbers}
        try:
            readings = {page: self._lvm.read_page(images[page]) for page in page_numbers}
        finally:
            self._lvm.release()

        ocr_tables: dict[int, list[list[list[str]]]] = {}
        pages_with_tables = [page for page in page_numbers if readings[page].tables]
        if pages_with_tables:
            try:
                ocr_tables = {
                    page: self._table_ocr.read_tables(images[page]) for page in pages_with_tables
                }
            finally:
                self._table_ocr.release()

        return {
            page: _blocks(readings[page], ocr_tables.get(page, []), page) for page in page_numbers
        }


def _blocks(
    reading: PageReading, ocr_tables: list[list[list[str]]], page_number: int
) -> list[ContentBlock]:
    blocks: list[ContentBlock] = []
    for item in reading.items:
        if isinstance(item, str):
            if item.strip():
                blocks.append(
                    ContentBlock.paragraph(
                        order=0, text=item, page_number=page_number, source=ContentSource.LVM
                    )
                )
            continue
        grid = [list(item.header), *(list(row) for row in item.rows)]
        if not any(cell.strip() for row in grid for cell in row):
            continue
        blocks.append(
            ContentBlock.table(
                order=0,
                rows=grid,
                page_number=page_number,
                source=ContentSource.LVM,
                review_reason=find_table_review_reason(
                    header=item.header,
                    rows=item.rows,
                    row_labels=item.row_labels,
                    ocr_tables=ocr_tables,
                ),
            )
        )
    return blocks
