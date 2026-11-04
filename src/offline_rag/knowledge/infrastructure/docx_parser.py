"""DOCX files read with python-docx (ADR 0002)."""

import io
import zipfile

import docx
from docx.document import Document
from docx.opc.exceptions import PackageNotFoundError
from docx.table import Table
from docx.text.paragraph import Paragraph

from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.extracted_content import ContentBlock, ExtractedContent
from offline_rag.knowledge.infrastructure.errors import DocumentExtractionError

_HEADING_STYLE_PREFIX = "Heading "
_TITLE_STYLE = "Title"


class DocxParser:
    """Turns a DOCX file into blocks under the headings they belong to.

    Consecutive paragraphs under the same heading become one text block, one
    paragraph per line. Each table becomes a table block. Headings are not blocks;
    they make up the `heading_path` of the blocks below them.
    """

    def parse(
        self, content: bytes, document_format: DocumentFormat = DocumentFormat.DOCX
    ) -> ExtractedContent:
        """Return the blocks of a DOCX file.

        Args:
            content: The DOCX file.
            document_format: The format recorded on the result. DOC files are
                converted to DOCX first and keep `DocumentFormat.DOC` here.

        Raises:
            DocumentExtractionError: The file is not a readable DOCX file.
        """
        try:
            document = docx.Document(io.BytesIO(content))
            blocks = _blocks(document)
        except (
            PackageNotFoundError,
            zipfile.BadZipFile,
            KeyError,
            ValueError,
            # lxml's XMLSyntaxError, raised for broken XML inside the file, is a SyntaxError.
            SyntaxError,
        ) as error:
            raise DocumentExtractionError(document_format.value) from error
        return ExtractedContent(
            document_format=document_format, page_count=None, blocks=tuple(blocks)
        )


def _blocks(document: Document) -> list[ContentBlock]:
    blocks: list[ContentBlock] = []
    headings: list[tuple[int, str]] = []
    paragraph_lines: list[str] = []

    def flush_paragraphs() -> None:
        if paragraph_lines:
            blocks.append(
                ContentBlock.paragraph(
                    order=len(blocks),
                    text="\n".join(paragraph_lines),
                    heading_path=tuple(text for _, text in headings),
                )
            )
            paragraph_lines.clear()

    for element in document.element.body.iterchildren():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph = Paragraph(element, document)
            text = paragraph.text.strip()
            if not text:
                continue
            level = _heading_level(paragraph)
            if level is None:
                paragraph_lines.append(text)
                continue
            flush_paragraphs()
            headings[:] = [(lvl, txt) for lvl, txt in headings if lvl < level]
            headings.append((level, text))
        elif tag == "tbl":
            flush_paragraphs()
            rows = _table_rows(Table(element, document))
            if rows:
                blocks.append(
                    ContentBlock.table(
                        order=len(blocks),
                        rows=rows,
                        heading_path=tuple(text for _, text in headings),
                    )
                )
    flush_paragraphs()
    return blocks


def _heading_level(paragraph: Paragraph) -> int | None:
    style_name = paragraph.style.name if paragraph.style is not None else ""
    if style_name == _TITLE_STYLE:
        return 0
    if style_name.startswith(_HEADING_STYLE_PREFIX):
        level = style_name.removeprefix(_HEADING_STYLE_PREFIX)
        return int(level) if level.isdigit() else None
    return None


def _table_rows(table: Table) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in table.rows:
        cells: list[str] = []
        previous_cell = None
        for cell in row.cells:
            # python-docx repeats a merged cell once per grid column it spans.
            if cell._tc is previous_cell:
                continue
            previous_cell = cell._tc
            cells.append(cell.text)
        if any(text.strip() for text in cells):
            rows.append(cells)
    return rows
