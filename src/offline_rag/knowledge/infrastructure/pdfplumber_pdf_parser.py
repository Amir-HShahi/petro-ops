"""PDF files with a text layer read with pdfplumber (ADR 0002)."""

import io
import re
from typing import Any

import pdfplumber
from pdfminer.psparser import PSException
from pdfplumber.page import Page
from pdfplumber.utils.exceptions import MalformedPDFException, PdfminerException

from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.extracted_content import ContentBlock, ExtractedContent
from offline_rag.knowledge.infrastructure.errors import DocumentExtractionError

# pdfminer writes glyphs it cannot map, such as bullets, as "(cid:127)".
_UNMAPPED_GLYPH = re.compile(r"\(cid:\d+\)\s?")

BoundingBox = tuple[float, float, float, float]


class PdfplumberPdfParser:
    """Turns each PDF page into text blocks and table blocks, top to bottom.

    Text between two tables, or between a table and the page edge, becomes one
    block. A page without a text layer gives no blocks; the page count still
    includes it, so the LVM step can find it.
    """

    def parse(self, content: bytes) -> ExtractedContent:
        """Return the blocks of a PDF file.

        Raises:
            DocumentExtractionError: The file is not a readable PDF, or is encrypted.
        """
        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                blocks: list[ContentBlock] = []
                for page_number, page in enumerate(pdf.pages, start=1):
                    _add_page_blocks(blocks, page, page_number)
                page_count = len(pdf.pages)
        except (PdfminerException, MalformedPDFException, PSException, ValueError) as error:
            raise DocumentExtractionError(DocumentFormat.PDF.value) from error
        return ExtractedContent(
            document_format=DocumentFormat.PDF, page_count=page_count, blocks=tuple(blocks)
        )


def _add_page_blocks(blocks: list[ContentBlock], page: Page, page_number: int) -> None:
    tables = page.find_tables()
    table_boxes = [table.bbox for table in tables]
    text_page = page.filter(lambda obj: not _is_inside_any(obj, table_boxes))

    items: list[tuple[float, str | list[list[str]]]] = [
        (line["top"], _UNMAPPED_GLYPH.sub("", line["text"]))
        for line in text_page.extract_text_lines()
    ]
    items += [
        (table.bbox[1], [[cell or "" for cell in row] for row in table.extract()])
        for table in tables
    ]
    items.sort(key=lambda item: item[0])

    lines: list[str] = []
    for _, item in items:
        if isinstance(item, str):
            if item.strip():
                lines.append(item)
            continue
        _flush_lines(blocks, lines, page_number)
        rows = [row for row in item if any(cell.strip() for cell in row)]
        if rows:
            blocks.append(ContentBlock.table(order=len(blocks), rows=rows, page_number=page_number))
    _flush_lines(blocks, lines, page_number)


def _flush_lines(blocks: list[ContentBlock], lines: list[str], page_number: int) -> None:
    if lines:
        blocks.append(
            ContentBlock.paragraph(
                order=len(blocks), text="\n".join(lines), page_number=page_number
            )
        )
        lines.clear()


def _is_inside_any(obj: dict[str, Any], boxes: list[BoundingBox]) -> bool:
    if "x0" not in obj or "top" not in obj:
        return False
    center_x = (obj["x0"] + obj["x1"]) / 2
    center_y = (obj["top"] + obj["bottom"]) / 2
    return any(x0 <= center_x <= x1 and top <= center_y <= bottom for x0, top, x1, bottom in boxes)
