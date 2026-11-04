"""Errors raised by the Knowledge Management adapters.

Messages never name file paths or library errors; those go to the logs.
"""

from offline_rag.shared_kernel.errors import InfrastructureError


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
    """A submitted file could not be written to or read from the local file store."""

    code = "KNOWLEDGE_SOURCE_FILE_STORAGE_FAILED"

    def __init__(self, file_name: str) -> None:
        """Create the error for the file that could not be stored."""
        super().__init__(
            f"The file '{file_name}' could not be stored. "
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
