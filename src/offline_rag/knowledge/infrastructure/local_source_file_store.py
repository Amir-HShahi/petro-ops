"""Original submitted files kept in a local folder (spec §17, ADR 0003)."""

import os
import re
import tempfile
import uuid
from pathlib import Path

from offline_rag.knowledge.infrastructure.errors import SourceFileStorageError

_SAFE_SUFFIX = re.compile(r"\.[a-z0-9]{1,8}")
# Only names this store made can be read back, so a reference is never a path.
_REFERENCE = re.compile(r"[0-9a-f]{32}(?:\.[a-z0-9]{1,8})?")


class LocalSourceFileStore:
    """Writes each file under a new random name, so no two files collide.

    The submitted file name is never used as a path, only its suffix is kept, so
    a name such as `../../x.pdf` cannot write outside the folder.
    """

    def __init__(self, root: Path) -> None:
        """Use `root` as the folder, creating it when it is missing.

        Raises:
            SourceFileStorageError: The folder cannot be created.
        """
        self._root = root
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise SourceFileStorageError(root.name) from error

    def save(self, file_name: str, content: bytes) -> str:
        """Store the file and return its reference, the name of the stored file.

        Raises:
            SourceFileStorageError: The file cannot be written.
        """
        suffix = Path(file_name).suffix.lower()
        reference = uuid.uuid4().hex + (suffix if _SAFE_SUFFIX.fullmatch(suffix) else "")
        try:
            # Write to a temporary file first, so a crash never leaves half a file.
            with tempfile.NamedTemporaryFile(dir=self._root, delete=False) as temporary:
                temporary.write(content)
            os.replace(temporary.name, self._root / reference)
        except OSError as error:
            raise SourceFileStorageError(file_name) from error
        return reference

    def read(self, reference: str) -> bytes:
        """Return the file stored under `reference`.

        Raises:
            SourceFileStorageError: The reference is not one this store made, or
                the file is missing or cannot be read.
        """
        if not _REFERENCE.fullmatch(reference):
            raise SourceFileStorageError(reference)
        try:
            return (self._root / reference).read_bytes()
        except OSError as error:
            raise SourceFileStorageError(reference) from error
