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

from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.extracted_content import (
    TABLE_CELL_SEPARATOR,
    ContentBlock,
    ExtractedContent,
    normalize_extracted_text,
)
from offline_rag.knowledge.infrastructure.docling_document_parser import DoclingDocumentParser
from offline_rag.knowledge.infrastructure.libreoffice_doc_converter import (
    LibreOfficeDocConverter,
)
from offline_rag.settings import Settings

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parents[3] / "fixtures"
# These have no text layer; their quotes are the LVM's job (ADR 0002).
DOCUMENTS_WITHOUT_TEXT_LAYER = {"scan-01", "pub-cullen-piper-alpha"}
IS_LIBREOFFICE_INSTALLED = shutil.which("soffice") is not None
MODELS_DIR = Settings().docling_models_dir
# PDF quotes need Docling's layout and table models, which are slow to run.
PDF_MARKS = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not MODELS_DIR.is_dir(),
        reason=f"Docling models missing: docling-tools models download layout tableformer "
        f"-o {MODELS_DIR}",
    ),
]


def _manifest() -> dict[str, dict[str, str]]:
    with (FIXTURES / "docs" / "manifest.csv").open(newline="", encoding="utf-8") as manifest:
        return {row["id"]: row for row in csv.DictReader(manifest)}


def _evidence() -> list[pytest.ParameterSet]:
    manifest = _manifest()
    found = []
    for golden_file in sorted((FIXTURES / "golden").glob("*.jsonl")):
        for line in golden_file.read_text(encoding="utf-8").splitlines():
            for evidence in json.loads(line)["evidence"]:
                doc_id = evidence["doc_id"]
                if doc_id in DOCUMENTS_WITHOUT_TEXT_LAYER:
                    continue
                found.append(
                    pytest.param(
                        doc_id,
                        evidence["page_or_section"],
                        evidence["quote"],
                        marks=PDF_MARKS if manifest[doc_id]["format"] == "pdf" else [],
                    )
                )
    return found


@cache
def _parser() -> DoclingDocumentParser:
    return DoclingDocumentParser(
        models_dir=MODELS_DIR,
        doc_converter=LibreOfficeDocConverter(soffice_path="soffice", timeout_s=120),
    )


@cache
def _extract(doc_id: str) -> ExtractedContent:
    row = _manifest()[doc_id]
    content = (FIXTURES / "docs" / row["file"]).read_bytes()
    return _parser().parse(content, DocumentFormat(row["format"]))


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
