"""Legacy DOC files converted to DOCX with LibreOffice headless (ADR 0007)."""

import shutil
import subprocess
import tempfile
from pathlib import Path

from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.infrastructure.errors import (
    DocConverterUnavailableError,
    DocumentExtractionError,
)


class LibreOfficeDocConverter:
    """Runs `soffice --convert-to docx` in a temporary folder, offline."""

    def __init__(self, *, soffice_path: str, timeout_s: int) -> None:
        """Create the converter.

        Args:
            soffice_path: The `soffice` program, as a name on PATH or a full path.
            timeout_s: How long one conversion may take before it is stopped.
        """
        self._soffice_path = soffice_path
        self._timeout_s = timeout_s

    def convert(self, content: bytes) -> bytes:
        """Return a DOC file converted to DOCX.

        Raises:
            DocConverterUnavailableError: LibreOffice is missing or timed out.
            DocumentExtractionError: LibreOffice could not convert the file.
        """
        soffice = shutil.which(self._soffice_path)
        if soffice is None:
            raise DocConverterUnavailableError

        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            source = work / "source.doc"
            source.write_bytes(content)
            command = [
                soffice,
                # A private profile lets conversions run while LibreOffice is open.
                f"-env:UserInstallation={(work / 'profile').as_uri()}",
                "--headless",
                "--convert-to",
                "docx",
                "--outdir",
                str(work),
                str(source),
            ]
            try:
                subprocess.run(command, capture_output=True, timeout=self._timeout_s, check=False)
            except subprocess.TimeoutExpired as error:
                raise DocConverterUnavailableError from error
            except OSError as error:
                raise DocConverterUnavailableError from error

            converted = work / "source.docx"
            if not converted.is_file():
                raise DocumentExtractionError(DocumentFormat.DOC.value)
            return converted.read_bytes()
