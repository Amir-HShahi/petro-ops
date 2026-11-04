"""Every golden evidence quote must be found where the golden set says it is.

This is the extraction half of Recall@5 in `docs/evaluation-baseline.md`: a quote
that extraction loses or puts on the wrong page can never be retrieved.
"""

import csv
import json
import re
import shutil
from functools import cache
from pathlib import Path

import pytest

from offline_rag.knowledge.domain.extracted_content import (
    TABLE_CELL_SEPARATOR,
    ContentBlock,
    ExtractedContent,
    normalize_extracted_text,
)
from offline_rag.knowledge.infrastructure.docx_parser import DocxParser
from offline_rag.knowledge.infrastructure.libreoffice_doc_parser import LibreOfficeDocParser
from offline_rag.knowledge.infrastructure.pdfplumber_pdf_parser import PdfplumberPdfParser

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parents[3] / "fixtures"
# These have no text layer; their quotes are the LVM's job (ADR 0002).
DOCUMENTS_WITHOUT_TEXT_LAYER = {"scan-01", "pub-cullen-piper-alpha"}
IS_LIBREOFFICE_INSTALLED = shutil.which("soffice") is not None


def _manifest() -> dict[str, dict[str, str]]:
    with (FIXTURES / "docs" / "manifest.csv").open(newline="", encoding="utf-8") as manifest:
        return {row["id"]: row for row in csv.DictReader(manifest)}


def _evidence() -> list[tuple[str, str, str]]:
    found = []
    for golden_file in sorted((FIXTURES / "golden").glob("*.jsonl")):
        for line in golden_file.read_text(encoding="utf-8").splitlines():
            for evidence in json.loads(line)["evidence"]:
                if evidence["doc_id"] not in DOCUMENTS_WITHOUT_TEXT_LAYER:
                    found.append(
                        (evidence["doc_id"], evidence["page_or_section"], evidence["quote"])
                    )
    return found


@cache
def _extract(doc_id: str) -> ExtractedContent:
    row = _manifest()[doc_id]
    content = (FIXTURES / "docs" / row["file"]).read_bytes()
    match row["format"]:
        case "pdf":
            return PdfplumberPdfParser().parse(content)
        case "docx":
            return DocxParser().parse(content)
        case _:
            parser = LibreOfficeDocParser(
                soffice_path="soffice", timeout_s=120, docx_parser=DocxParser()
            )
            return parser.parse(content)


def _flatten(text: str) -> str:
    return re.sub(r"\s+", " ", normalize_extracted_text(text))


def _is_at(block: ContentBlock, page_or_section: str) -> bool:
    if page_or_section.startswith("page "):
        return block.page_number == int(page_or_section.removeprefix("page "))
    return bool(block.heading_path) and block.heading_path[-1] == page_or_section


@pytest.mark.parametrize(
    ("doc_id", "page_or_section", "quote"),
    _evidence(),
    ids=lambda value: value if len(value) < 40 else value[:37] + "...",
)
def test_golden_quote_is_extracted_at_its_page_or_section_when_document_is_parsed(
    doc_id: str, page_or_section: str, quote: str
):
    if _manifest()[doc_id]["format"] == "doc" and not IS_LIBREOFFICE_INSTALLED:
        pytest.skip("DOC extraction needs LibreOffice")
    blocks = [block for block in _extract(doc_id).blocks if _is_at(block, page_or_section)]

    # Some golden quotes of PDF table rows were taken from plain text, without the
    # cell separator, so both forms count.
    texts = [_flatten(block.text) for block in blocks]
    texts += [text.replace(TABLE_CELL_SEPARATOR, " ") for text in texts]
    assert any(_flatten(quote) in text for text in texts), (doc_id, page_or_section)
