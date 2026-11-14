"""Errors raised by the Issue Management use cases and repositories."""

from offline_rag.shared_kernel.errors import NotFoundError
from offline_rag.shared_kernel.node_identifier import NodeIdentifier


class IssueNotFoundError(NotFoundError):
    """No Issue has the requested id."""

    code = "ISSUE_NOT_FOUND"

    def __init__(self, issue_id: str) -> None:
        """Create the error for the missing Issue."""
        super().__init__(
            f"Issue '{issue_id}' does not exist. Check the id that `issue raise` printed.",
            details={"issue_id": issue_id},
        )


class OwnerNodeNotFoundError(NotFoundError):
    """An Issue was raised for a Node that is not registered (spec §12)."""

    code = "ISSUE_OWNER_NODE_NOT_FOUND"

    def __init__(self, node_id: NodeIdentifier) -> None:
        """Create the error for the unknown Node."""
        super().__init__(
            f"Node '{node_id.value}' is not registered. Register the Node before raising "
            "Issues for it.",
            details={"node_id": node_id.value},
        )
