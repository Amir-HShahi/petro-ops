"""Errors raised at the Organizational Hierarchy entry points."""

from offline_rag.shared_kernel.errors import DomainError, NotFoundError


class NodeRegistryFileNotReadableError(NotFoundError):
    """The Node registry file to import does not exist or cannot be read."""

    code = "ORGANIZATION_NODE_REGISTRY_FILE_NOT_READABLE"

    def __init__(self, file_name: str) -> None:
        """Create the error for the unreadable file."""
        super().__init__(
            f"The Node registry file '{file_name}' cannot be read. Check the path.",
            details={"file_name": file_name},
        )


class NodeRegistryFileInvalidError(DomainError):
    """A row of the Node registry file is missing a column or has a value it cannot hold."""

    code = "ORGANIZATION_NODE_REGISTRY_FILE_INVALID"

    def __init__(self, *, row_number: int, column: str, value: str | None) -> None:
        """Create the error.

        Args:
            row_number: The data row, counted from 1 after the header.
            column: The column that is missing or wrong.
            value: What the row holds there; None when the column is missing.
        """
        super().__init__(
            f"Row {row_number} of the Node registry file has no valid '{column}'. "
            "Fix it as described in fixtures/registry/README.md.",
            details={"row_number": row_number, "column": column, "value": value},
        )
