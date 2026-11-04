"""Errors raised by the Knowledge Management entry points."""

from offline_rag.shared_kernel.errors import NotFoundError


class SourceFileNotReadableError(NotFoundError):
    """The file named on the command line does not exist or cannot be read."""

    code = "KNOWLEDGE_SOURCE_FILE_NOT_READABLE"

    def __init__(self, file_name: str) -> None:
        """Create the error for the file that could not be read."""
        super().__init__(
            f"The file '{file_name}' does not exist or cannot be read. Check the path.",
            details={"file_name": file_name},
        )
