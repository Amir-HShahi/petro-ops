"""File formats the core accepts (spec §7.3) and how to recognize them."""

from enum import StrEnum

from offline_rag.knowledge.domain.errors import (
    EmptySourceFileError,
    UnsupportedDocumentFormatError,
)


class DocumentFormat(StrEnum):
    """File format of a submitted source file (spec §5, §7.3)."""

    DOC = "doc"
    DOCX = "docx"
    PDF = "pdf"


_SIGNATURES = (
    (b"%PDF-", DocumentFormat.PDF),
    (b"PK\x03\x04", DocumentFormat.DOCX),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", DocumentFormat.DOC),
)


def detect_document_format(content: bytes, *, file_name: str) -> DocumentFormat:
    """Return the format of a file from its first bytes, never from its name.

    A DOCX file is a ZIP archive and a DOC file is an OLE compound file, so other
    files of those container types, such as XLSX or XLS, pass here. The parser
    rejects them later when it opens them.

    Args:
        content: The whole file.
        file_name: The name the file was submitted with, used only in error messages.

    Raises:
        EmptySourceFileError: The file has no content.
        UnsupportedDocumentFormatError: The file is not DOC, DOCX or PDF.
    """
    if not content:
        raise EmptySourceFileError(file_name)
    for signature, document_format in _SIGNATURES:
        if content.startswith(signature):
            return document_format
    raise UnsupportedDocumentFormatError(file_name)
