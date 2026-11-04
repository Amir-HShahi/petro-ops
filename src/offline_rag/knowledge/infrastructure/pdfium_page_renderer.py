"""PDF pages drawn as PNG images with pypdfium2, for the vision models (ADR 0002)."""

import io

import pypdfium2

from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.infrastructure.errors import DocumentExtractionError

_PDF_POINTS_PER_INCH = 72


class PdfiumPageRenderer:
    """Renders one page at a fixed resolution."""

    def __init__(self, *, dpi: int) -> None:
        """Render at `dpi` dots per inch. The benchmark in ADR 0002 used 150."""
        self._scale = dpi / _PDF_POINTS_PER_INCH

    def render(self, pdf: bytes, page_number: int) -> bytes:
        """Return page `page_number`, starting at 1, as a PNG image.

        Raises:
            DocumentExtractionError: The file is not a readable PDF or has no such page.
        """
        try:
            document = pypdfium2.PdfDocument(pdf)
            try:
                if not 1 <= page_number <= len(document):
                    raise DocumentExtractionError(DocumentFormat.PDF.value)
                image = document[page_number - 1].render(scale=self._scale).to_pil()
            finally:
                document.close()
        except pypdfium2.PdfiumError as error:
            raise DocumentExtractionError(DocumentFormat.PDF.value) from error

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()
