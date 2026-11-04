"""The `DocumentParser` port, routing each format to its local parser."""

from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.extracted_content import ExtractedContent
from offline_rag.knowledge.infrastructure.docx_parser import DocxParser
from offline_rag.knowledge.infrastructure.libreoffice_doc_parser import LibreOfficeDocParser
from offline_rag.knowledge.infrastructure.pdfplumber_pdf_parser import PdfplumberPdfParser


class LocalDocumentParser:
    """Reads DOC, DOCX and PDF files with local libraries only; nothing leaves the machine."""

    def __init__(
        self,
        *,
        docx_parser: DocxParser,
        pdf_parser: PdfplumberPdfParser,
        doc_parser: LibreOfficeDocParser,
    ) -> None:
        """Create the parser from one parser per format."""
        self._docx_parser = docx_parser
        self._pdf_parser = pdf_parser
        self._doc_parser = doc_parser

    def parse(self, content: bytes, document_format: DocumentFormat) -> ExtractedContent:
        """Return the blocks of a file, read with the parser for its format."""
        match document_format:
            case DocumentFormat.DOCX:
                return self._docx_parser.parse(content)
            case DocumentFormat.PDF:
                return self._pdf_parser.parse(content)
            case DocumentFormat.DOC:
                return self._doc_parser.parse(content)
