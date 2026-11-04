"""Errors raised by the Knowledge Management adapters.

Messages never name file paths or library errors; those go to the logs.
"""

from offline_rag.shared_kernel.errors import DomainError, InfrastructureError


class KnowledgeStorageError(InfrastructureError):
    """The local knowledge database could not be read or written."""

    code = "KNOWLEDGE_STORAGE_FAILED"

    def __init__(self, operation: str) -> None:
        """Create the error.

        Args:
            operation: What was being done, such as `add` or `get_by_id`.
        """
        super().__init__(
            "The local knowledge database is not available. Try again, or check the data folder.",
            details={"operation": operation},
        )


class SourceFileStorageError(InfrastructureError):
    """A file could not be written to or read from the local file store."""

    code = "KNOWLEDGE_SOURCE_FILE_STORAGE_FAILED"

    def __init__(self, file_name: str) -> None:
        """Create the error for the file that could not be stored or read."""
        super().__init__(
            f"The file '{file_name}' could not be stored or read. "
            "Check free disk space and the data folder.",
            details={"file_name": file_name},
        )


class NodeRegistryUnavailableError(InfrastructureError):
    """The Node registry file is missing or does not have the expected columns."""

    code = "KNOWLEDGE_NODE_REGISTRY_UNAVAILABLE"

    def __init__(self) -> None:
        """Create the error."""
        super().__init__(
            "The Node registry could not be read. Check NODE_REGISTRY_PATH and the file's columns.",
        )


class DocumentExtractionError(DomainError):
    """A file could not be read as the format its first bytes claim (spec §7.3)."""

    code = "KNOWLEDGE_EXTRACTION_FAILED"

    def __init__(self, document_format: str) -> None:
        """Create the error for the file that could not be parsed."""
        super().__init__(
            f"The file could not be read as {document_format.upper()}. It may be damaged, "
            "password protected or another file type. Open and save it again, then resubmit.",
            details={"document_format": document_format},
        )


class DocConverterUnavailableError(InfrastructureError):
    """DOC files need LibreOffice to be converted, and it is missing or failed (ADR 0002)."""

    code = "KNOWLEDGE_DOC_CONVERTER_UNAVAILABLE"

    def __init__(self) -> None:
        """Create the error."""
        super().__init__(
            "DOC files need LibreOffice, which is not installed or did not finish in time. "
            "Install LibreOffice or set LIBREOFFICE_PATH, then extract the item again.",
        )
