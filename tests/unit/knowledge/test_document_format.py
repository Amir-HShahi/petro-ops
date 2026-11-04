import pytest
from hypothesis import given
from hypothesis import strategies as st

from offline_rag.knowledge.domain.document_format import DocumentFormat, detect_document_format
from offline_rag.knowledge.domain.errors import (
    EmptySourceFileError,
    UnsupportedDocumentFormatError,
)

PDF_START = b"%PDF-1.7\n"
DOCX_START = b"PK\x03\x04\x14\x00\x06\x00"
DOC_START = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1\x00\x00"


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (PDF_START, DocumentFormat.PDF),
        (DOCX_START, DocumentFormat.DOCX),
        (DOC_START, DocumentFormat.DOC),
    ],
)
def test_format_is_detected_from_first_bytes_when_file_is_supported(
    content: bytes, expected: DocumentFormat
):
    assert detect_document_format(content, file_name="report") == expected


@given(rest=st.binary(max_size=64))
def test_format_ignores_the_rest_of_the_file_when_signature_matches(rest: bytes):
    assert detect_document_format(PDF_START + rest, file_name="report.pdf") == DocumentFormat.PDF


def test_format_ignores_the_file_name_when_extension_is_wrong():
    assert detect_document_format(PDF_START, file_name="report.docx") == DocumentFormat.PDF


@pytest.mark.parametrize(
    "content",
    [
        b"plain text, not a document",
        b"\x89PNG\r\n\x1a\n",
        b"%PD",
        b" %PDF-1.7",
    ],
)
def test_file_is_rejected_when_format_is_not_supported(content: bytes):
    with pytest.raises(UnsupportedDocumentFormatError) as caught:
        detect_document_format(content, file_name="photo.png")

    assert caught.value.code == "KNOWLEDGE_UNSUPPORTED_FORMAT"
    assert caught.value.details["file_name"] == "photo.png"


def test_file_is_rejected_when_it_is_empty():
    with pytest.raises(EmptySourceFileError) as caught:
        detect_document_format(b"", file_name="empty.pdf")

    assert caught.value.code == "KNOWLEDGE_EMPTY_FILE"
