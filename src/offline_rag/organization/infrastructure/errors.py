"""Errors raised by the Organizational Hierarchy adapters.

Messages never name file paths or library errors; those go to the logs.
"""

from offline_rag.shared_kernel.errors import InfrastructureError


class OrganizationStorageError(InfrastructureError):
    """The local database of Nodes and Layers could not be read or written."""

    code = "ORGANIZATION_STORAGE_FAILED"

    def __init__(self, operation: str) -> None:
        """Create the error.

        Args:
            operation: What was being done, such as `add` or `get_by_id`.
        """
        super().__init__(
            "The local organization database is not available. Check that Postgres is "
            "running and the migrations have run, then try again.",
            details={"operation": operation},
        )
