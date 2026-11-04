"""DOC, DOCX and text-layer PDF files read with Docling from local models (ADR 0007)."""

import io
from collections.abc import Iterator
from pathlib import Path

from docling.datamodel.base_models import ConversionStatus, DocumentStream, InputFormat
from docling.datamodel.pipeline_options import LayoutObjectDetectionOptions, PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.exceptions import ConversionError
from docling.models.stages.table_structure.table_structure_model import TableStructureModel
from docling_core.types.doc.document import DoclingDocument
from docling_core.types.doc.items.node import DocItem, NodeItem
from docling_core.types.doc.items.table.table import TableItem
from docling_core.types.doc.items.text import SectionHeaderItem, TextItem, TitleItem

from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.extracted_content import ContentBlock, ExtractedContent
from offline_rag.knowledge.infrastructure.errors import (
    DocumentExtractionError,
    DocumentParserModelsUnavailableError,
)
from offline_rag.knowledge.infrastructure.libreoffice_doc_converter import LibreOfficeDocConverter

# The folders `docling-tools models download layout tableformer` writes.
_MODEL_FOLDERS = (
    LayoutObjectDetectionOptions().model_spec.repo_id.replace("/", "--"),
    TableStructureModel._model_repo_folder,
)
_TITLE_LEVEL = 0


class DoclingDocumentParser:
    """Turns a file into text blocks and table blocks in reading order.

    PDF: text between two tables on a page becomes one block, with its page
    number. OCR is off, so a page without a text layer gives no blocks; the page
    count still includes it, so the LVM step can find it (ADR 0002).

    DOC and DOCX: consecutive paragraphs under the same heading become one block,
    one paragraph per line. Headings are not blocks; they make up the
    `heading_path` of the blocks below them. DOC is converted to DOCX first.
    """

    def __init__(self, *, models_dir: Path, doc_converter: LibreOfficeDocConverter) -> None:
        """Create the parser.

        Args:
            models_dir: The folder with Docling's layout and table-structure models.
                Models are loaded only from here; nothing is downloaded.
            doc_converter: Converts DOC files to DOCX.
        """
        self._models_dir = models_dir
        self._doc_converter = doc_converter
        pdf_options = PdfPipelineOptions(
            artifacts_path=models_dir,
            enable_remote_services=False,
            do_ocr=False,
            do_table_structure=True,
        )
        # One converter per format, so a file whose content is another allowed
        # format is refused instead of being read as that format.
        self._pdf_converter = DocumentConverter(
            allowed_formats=[InputFormat.PDF],
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options)},
        )
        self._docx_converter = DocumentConverter(allowed_formats=[InputFormat.DOCX])

    def parse(self, content: bytes, document_format: DocumentFormat) -> ExtractedContent:
        """Return the blocks of a file in reading order, with normalized text.

        Raises:
            DocumentExtractionError: The file cannot be read as its format.
            DocConverterUnavailableError: A DOC file needs LibreOffice, which is missing.
            DocumentParserModelsUnavailableError: The layout or table models are missing.
        """
        match document_format:
            case DocumentFormat.PDF:
                self._require_models()
                document = _convert(self._pdf_converter, content, document_format)
                return ExtractedContent(
                    document_format=document_format,
                    page_count=len(document.pages),
                    blocks=tuple(_blocks(document, is_paged=True)),
                )
            case DocumentFormat.DOCX:
                document = _convert(self._docx_converter, content, document_format)
            case DocumentFormat.DOC:
                docx_content = self._doc_converter.convert(content)
                document = _convert(self._docx_converter, docx_content, document_format)
        return ExtractedContent(
            document_format=document_format,
            page_count=None,
            blocks=tuple(_blocks(document, is_paged=False)),
        )

    def _require_models(self) -> None:
        missing = [name for name in _MODEL_FOLDERS if not (self._models_dir / name).is_dir()]
        if missing:
            raise DocumentParserModelsUnavailableError(missing)


def _convert(
    converter: DocumentConverter, content: bytes, document_format: DocumentFormat
) -> DoclingDocument:
    # A DOC file reaches Docling as DOCX after its LibreOffice conversion.
    suffix = "pdf" if document_format == DocumentFormat.PDF else "docx"
    source = DocumentStream(name=f"source.{suffix}", stream=io.BytesIO(content))
    try:
        result = converter.convert(source, raises_on_error=False)
    except ConversionError as error:
        raise DocumentExtractionError(document_format.value) from error
    if result.status != ConversionStatus.SUCCESS:
        raise DocumentExtractionError(document_format.value)
    return result.document


def _items(document: DoclingDocument) -> Iterator[NodeItem]:
    """Yield the body items in reading order, without the items inside tables.

    Docling also lists each table cell's text as a child item; the table block
    already holds it. Text inside figures is kept, since it is text-layer text.
    """
    table_level: int | None = None
    for item, level in document.iterate_items(traverse_pictures=True):
        if table_level is not None and level > table_level:
            continue
        table_level = level if isinstance(item, TableItem) else None
        yield item


def _blocks(document: DoclingDocument, *, is_paged: bool) -> list[ContentBlock]:
    blocks: list[ContentBlock] = []
    headings: list[tuple[int, str]] = []
    lines: list[str] = []
    lines_page: int | None = None

    def heading_path() -> tuple[str, ...]:
        return tuple(text for _, text in headings)

    def flush_lines() -> None:
        if lines:
            blocks.append(
                ContentBlock.paragraph(
                    order=len(blocks),
                    text="\n".join(lines),
                    page_number=lines_page,
                    heading_path=heading_path(),
                )
            )
            lines.clear()

    for item in _items(document):
        page_number = _page_number(item) if is_paged else None
        if is_paged and page_number is None:
            continue
        if isinstance(item, TableItem):
            rows = _table_rows(item)
            if rows:
                flush_lines()
                blocks.append(
                    ContentBlock.table(
                        order=len(blocks),
                        rows=rows,
                        page_number=page_number,
                        heading_path=heading_path(),
                    )
                )
            continue
        if not isinstance(item, TextItem) or not item.text.strip():
            continue
        level = _heading_level(item)
        # A PDF heading stays in the page text; Docling cannot tell its level reliably.
        if level is not None and not is_paged:
            flush_lines()
            headings[:] = [(lvl, text) for lvl, text in headings if lvl < level]
            headings.append((level, item.text.strip()))
            continue
        if page_number != lines_page:
            flush_lines()
        lines.append(item.text)
        lines_page = page_number
    flush_lines()
    return blocks


def _page_number(item: NodeItem) -> int | None:
    if isinstance(item, DocItem) and item.prov:
        return item.prov[0].page_no
    return None


def _heading_level(item: TextItem) -> int | None:
    if isinstance(item, TitleItem):
        return _TITLE_LEVEL
    if isinstance(item, SectionHeaderItem):
        return item.level
    return None


def _table_rows(table: TableItem) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in table.data.grid:
        # The grid repeats a merged cell once per column it spans.
        cells = [
            cell.text for column, cell in enumerate(row) if cell.start_col_offset_idx == column
        ]
        if any(text.strip() for text in cells):
            rows.append(cells)
    return rows
