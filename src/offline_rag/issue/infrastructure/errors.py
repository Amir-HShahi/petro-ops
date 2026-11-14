"""Errors raised by the Issue Management adapters.

Messages never name file paths or library errors; those go to the logs.
"""

from offline_rag.shared_kernel.errors import InfrastructureError


class IssueStorageError(InfrastructureError):
    """The local database of Issues could not be read or written."""

    code = "ISSUE_STORAGE_FAILED"

    def __init__(self, operation: str) -> None:
        """Create the error.

        Args:
            operation: What was being done, such as `add` or `get_by_id`.
        """
        super().__init__(
            "The local Issue database is not available. Check that Postgres is running "
            "and the migrations have run, then try again.",
            details={"operation": operation},
        )


class NodeRegistryUnavailableError(InfrastructureError):
    """The registered Nodes of Organizational Hierarchy cannot be read."""

    code = "ISSUE_NODE_REGISTRY_UNAVAILABLE"

    def __init__(self) -> None:
        """Create the error."""
        super().__init__(
            "The registered Nodes could not be read. Check that Postgres is running "
            "and DATABASE_URL points to it.",
        )
