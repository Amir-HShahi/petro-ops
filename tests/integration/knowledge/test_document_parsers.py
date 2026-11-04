import shutil
from pathlib import Path

import pytest

from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.extracted_content import ContentBlockKind
from offline_rag.knowledge.infrastructure.docx_parser import DocxParser
from offline_rag.knowledge.infrastructure.errors import (
    DocConverterUnavailableError,
    DocumentExtractionError,
)
from offline_rag.knowledge.infrastructure.libreoffice_doc_parser import LibreOfficeDocParser
from offline_rag.knowledge.infrastructure.local_document_parser import LocalDocumentParser
from offline_rag.knowledge.infrastructure.pdfplumber_pdf_parser import PdfplumberPdfParser

pytestmark = pytest.mark.integration

DOCS = Path(__file__).parents[3] / "fixtures" / "docs"
INSPECTION_DOCX = DOCS / "synthetic" / "inspection_sp12_riser_r3_2024.docx"
PROJECT_PDF = DOCS / "synthetic" / "project_report_sp12_riser_r3_integrity.pdf"
SCANNED_PDF = DOCS / "cases" / "scanned_sp12_riser_r3_baseline_2021.pdf"
LEGACY_DOC = DOCS / "cases" / "legacy_riser_ut_inspection_procedure_2017.doc"
needs_libreoffice = pytest.mark.skipif(
    shutil.which("soffice") is None, reason="DOC extraction needs LibreOffice"
)


def test_docx_blocks_sit_under_their_headings_when_parsed():
    content = DocxParser().parse(INSPECTION_DOCX.read_bytes())

    sections = [block.heading_path[-1] for block in content.blocks]
    assert content.document_format == DocumentFormat.DOCX
    assert content.page_count is None
    assert "1. Scope" in sections
    assert "4. Recommendation" in sections


def test_docx_table_keeps_its_rows_and_cells_when_parsed():
    content = DocxParser().parse(INSPECTION_DOCX.read_bytes())

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


def test_pdf_blocks_keep_their_page_and_drop_unmapped_glyphs_when_parsed():
    content = PdfplumberPdfParser().parse(PROJECT_PDF.read_bytes())

    assert content.page_count == 2
    assert {block.page_number for block in content.blocks} == {1, 2}
    assert not any("(cid:" in block.text for block in content.blocks)
    assert any(block.kind == ContentBlockKind.TABLE for block in content.blocks)


def test_pdf_table_text_stays_out_of_the_text_blocks_when_parsed():
    content = PdfplumberPdfParser().parse(PROJECT_PDF.read_bytes())

    text_blocks = [block.text for block in content.blocks if block.kind == ContentBlockKind.TEXT]
    assert not any("Document ID" in text for text in text_blocks)


def test_scanned_pdf_page_is_left_for_the_lvm_when_it_has_no_text_layer():
    content = PdfplumberPdfParser().parse(SCANNED_PDF.read_bytes())

    assert content.page_count == 1
    assert content.blocks == ()
    assert content.pages_without_text(min_page_text_chars=20) == (1,)


@pytest.mark.parametrize(
    ("parse", "content"),
    [
        (DocxParser().parse, b"PK\x03\x04 not really a zip"),
        (DocxParser().parse, PROJECT_PDF.read_bytes()),
        (PdfplumberPdfParser().parse, b"%PDF-1.7 not really a pdf"),
        (PdfplumberPdfParser().parse, INSPECTION_DOCX.read_bytes()),
    ],
    ids=["broken-docx", "pdf-as-docx", "broken-pdf", "docx-as-pdf"],
)
def test_extraction_error_is_raised_when_file_is_not_its_format(parse, content: bytes):  # type: ignore[no-untyped-def]
    with pytest.raises(DocumentExtractionError) as caught:
        parse(content)

    assert caught.value.code == "KNOWLEDGE_EXTRACTION_FAILED"


def test_doc_converter_error_is_raised_when_libreoffice_is_missing():
    parser = LibreOfficeDocParser(
        soffice_path="soffice-that-does-not-exist", timeout_s=5, docx_parser=DocxParser()
    )

    with pytest.raises(DocConverterUnavailableError) as caught:
        parser.parse(LEGACY_DOC.read_bytes())

    assert caught.value.code == "KNOWLEDGE_DOC_CONVERTER_UNAVAILABLE"


@needs_libreoffice
def test_doc_is_converted_and_keeps_its_format_when_libreoffice_is_installed():
    parser = LibreOfficeDocParser(soffice_path="soffice", timeout_s=120, docx_parser=DocxParser())

    content = parser.parse(LEGACY_DOC.read_bytes())

    assert content.document_format == DocumentFormat.DOC
    assert content.blocks


@pytest.mark.parametrize(
    ("path", "document_format"),
    [(INSPECTION_DOCX, DocumentFormat.DOCX), (PROJECT_PDF, DocumentFormat.PDF)],
)
def test_each_format_goes_to_its_parser_when_parsed_locally(
    path: Path, document_format: DocumentFormat
):
    docx_parser = DocxParser()
    parser = LocalDocumentParser(
        docx_parser=docx_parser,
        pdf_parser=PdfplumberPdfParser(),
        doc_parser=LibreOfficeDocParser(
            soffice_path="soffice", timeout_s=120, docx_parser=docx_parser
        ),
    )

    assert parser.parse(path.read_bytes(), document_format).document_format == document_format
