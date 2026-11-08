import shutil
import socket
from pathlib import Path

import pytest

from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.extracted_content import ContentBlockKind
from offline_rag.knowledge.infrastructure.docling_document_parser import DoclingDocumentParser
from offline_rag.knowledge.infrastructure.errors import (
    DocConverterUnavailableError,
    DocumentExtractionError,
    DocumentParserModelsUnavailableError,
)
from offline_rag.knowledge.infrastructure.libreoffice_doc_converter import (
    LibreOfficeDocConverter,
)
from offline_rag.settings import Settings

pytestmark = pytest.mark.integration

DOCS = Path(__file__).parents[3] / "fixtures" / "docs"
INSPECTION_DOCX = DOCS / "synthetic" / "inspection_sp12_riser_r3_2024.docx"
PROJECT_PDF = DOCS / "synthetic" / "project_report_sp12_riser_r3_integrity.pdf"
SCANNED_PDF = DOCS / "cases" / "scanned_sp12_riser_r3_baseline_2021.pdf"
LEGACY_DOC = DOCS / "cases" / "legacy_riser_ut_inspection_procedure_2017.doc"
MODELS_DIR = Settings().docling_models_dir
needs_libreoffice = pytest.mark.skipif(
    shutil.which("soffice") is None, reason="DOC extraction needs LibreOffice"
)
# Reading a PDF loads Docling's layout and table models; tests doing so are also slow.
needs_docling_models = pytest.mark.skipif(
    not MODELS_DIR.is_dir(),
    reason=f"Docling models missing: docling-tools models download layout tableformer "
    f"-o {MODELS_DIR}",
)


def _parser(models_dir: Path = MODELS_DIR, soffice_path: str = "soffice") -> DoclingDocumentParser:
    return DoclingDocumentParser(
        models_dir=models_dir,
        doc_converter=LibreOfficeDocConverter(soffice_path=soffice_path, timeout_s=120),
    )


@pytest.fixture(scope="module")
def parser() -> DoclingDocumentParser:
    """One parser for the module, so the PDF models load once."""
    return _parser()


@pytest.fixture
def network_off(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise ConnectionRefusedError

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


def test_docx_blocks_sit_under_their_headings_when_parsed(parser: DoclingDocumentParser):
    content = parser.parse(INSPECTION_DOCX.read_bytes(), DocumentFormat.DOCX)

    sections = [block.heading_path[-1] for block in content.blocks]
    assert content.document_format == DocumentFormat.DOCX
    assert content.page_count is None
    assert "1. Scope" in sections
    assert "4. Recommendation" in sections


def test_docx_table_keeps_its_rows_and_cells_when_parsed(parser: DoclingDocumentParser):
    content = parser.parse(INSPECTION_DOCX.read_bytes(), DocumentFormat.DOCX)

    readings = next(
        block
        for block in content.blocks
        if block.kind == ContentBlockKind.TABLE and block.heading_path[-1] == "2. Readings"
    )
    assert readings.table_rows[0] == (
        "Location",
        "Nominal (mm)",
        "Measured (mm)",
        "Date",
        "Inspector",
    )
    assert all(len(row) == 5 for row in readings.table_rows)


def test_docx_table_cells_are_not_repeated_as_text_when_parsed(parser: DoclingDocumentParser):
    content = parser.parse(INSPECTION_DOCX.read_bytes(), DocumentFormat.DOCX)

    text_lines = {
        line
        for block in content.blocks
        if block.kind == ContentBlockKind.TEXT
        for line in block.text.split("\n")
    }
    assert "Measured (mm)" not in text_lines


@pytest.mark.slow
@needs_docling_models
def test_pdf_blocks_keep_their_page_when_parsed(parser: DoclingDocumentParser):
    content = parser.parse(PROJECT_PDF.read_bytes(), DocumentFormat.PDF)

    assert content.document_format == DocumentFormat.PDF
    assert content.page_count == 2
    assert {block.page_number for block in content.blocks} == {1, 2}
    assert all(not block.heading_path for block in content.blocks)
    assert any(block.kind == ContentBlockKind.TABLE for block in content.blocks)


@pytest.mark.slow
@needs_docling_models
def test_pdf_table_text_stays_out_of_the_text_blocks_when_parsed(parser: DoclingDocumentParser):
    content = parser.parse(PROJECT_PDF.read_bytes(), DocumentFormat.PDF)

    text_blocks = [block.text for block in content.blocks if block.kind == ContentBlockKind.TEXT]
    assert not any("Document ID" in text for text in text_blocks)


@pytest.mark.slow
@needs_docling_models
def test_scanned_pdf_page_is_left_for_the_lvm_when_it_has_no_text_layer(
    parser: DoclingDocumentParser,
):
    content = parser.parse(SCANNED_PDF.read_bytes(), DocumentFormat.PDF)

    assert content.page_count == 1
    assert content.blocks == ()
    assert content.pages_without_text(min_page_text_chars=20) == (1,)


@pytest.mark.slow
@needs_docling_models
@pytest.mark.usefixtures("network_off")
def test_pdf_is_parsed_from_local_models_when_the_network_is_off():
    content = _parser().parse(PROJECT_PDF.read_bytes(), DocumentFormat.PDF)

    assert content.blocks


def test_models_error_is_raised_when_the_models_folder_is_empty(tmp_path: Path):
    parser = _parser(models_dir=tmp_path)

    with pytest.raises(DocumentParserModelsUnavailableError) as caught:
        parser.parse(PROJECT_PDF.read_bytes(), DocumentFormat.PDF)

    assert caught.value.code == "KNOWLEDGE_PARSER_MODELS_UNAVAILABLE"
    assert len(caught.value.details["missing_models"]) == 2


@pytest.mark.parametrize(
    ("content", "document_format"),
    [
        pytest.param(b"PK\x03\x04 not really a zip", DocumentFormat.DOCX, id="broken-docx"),
        pytest.param(PROJECT_PDF.read_bytes(), DocumentFormat.DOCX, id="pdf-as-docx"),
        pytest.param(
            b"%PDF-1.7 not really a pdf",
            DocumentFormat.PDF,
            id="broken-pdf",
            marks=[pytest.mark.slow, needs_docling_models],
        ),
        pytest.param(
            INSPECTION_DOCX.read_bytes(),
            DocumentFormat.PDF,
            id="docx-as-pdf",
            marks=[pytest.mark.slow, needs_docling_models],
        ),
    ],
)
def test_extraction_error_is_raised_when_file_is_not_its_format(
    parser: DoclingDocumentParser, content: bytes, document_format: DocumentFormat
):
    with pytest.raises(DocumentExtractionError) as caught:
        parser.parse(content, document_format)

    assert caught.value.code == "KNOWLEDGE_EXTRACTION_FAILED"


def test_doc_converter_error_is_raised_when_libreoffice_is_missing():
    parser = _parser(soffice_path="soffice-that-does-not-exist")

    with pytest.raises(DocConverterUnavailableError) as caught:
        parser.parse(LEGACY_DOC.read_bytes(), DocumentFormat.DOC)

    assert caught.value.code == "KNOWLEDGE_DOC_CONVERTER_UNAVAILABLE"


@needs_libreoffice
def test_doc_is_converted_and_keeps_its_format_when_libreoffice_is_installed(
    parser: DoclingDocumentParser,
):
    content = parser.parse(LEGACY_DOC.read_bytes(), DocumentFormat.DOC)

    assert content.document_format == DocumentFormat.DOC
    assert content.page_count is None
    assert content.blocks
