"""Errors raised by the Issue Management use cases and repositories."""

from offline_rag.shared_kernel.errors import DomainError, NotFoundError
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


class KnowledgeRequiredError(DomainError):
    """An Issue was sent for decomposition without any knowledge to base it on (spec §12.5)."""

    code = "ISSUE_KNOWLEDGE_REQUIRED"

    def __init__(self, issue_id: str) -> None:
        """Create the error for the Issue that came without knowledge."""
        super().__init__(
            f"Name at least one KnowledgeItem to split Issue '{issue_id}', so every "
            "suggested SubIssue can cite its sources.",
            details={"issue_id": issue_id},
        )


class KnowledgeItemNotFoundError(NotFoundError):
    """A KnowledgeItem named for a decomposition does not exist."""

    code = "ISSUE_KNOWLEDGE_ITEM_NOT_FOUND"

    def __init__(self, item_id: str) -> None:
        """Create the error for the missing KnowledgeItem."""
        super().__init__(
            f"KnowledgeItem '{item_id}' does not exist. Use the item id that "
            "`knowledge submit` printed.",
            details={"item_id": item_id},
        )


class KnowledgeTooLargeError(DomainError):
    """The knowledge named for a decomposition does not fit in the model's context."""

    code = "ISSUE_KNOWLEDGE_TOO_LARGE"

    def __init__(self, *, token_count: int, limit_tokens: int) -> None:
        """Create the error for the knowledge that is too long."""
        super().__init__(
            f"The named KnowledgeItems hold about {token_count} tokens, but the model can "
            f"read about {limit_tokens} next to the prompt. Name fewer or shorter items.",
            details={"token_count": token_count, "limit_tokens": limit_tokens},
        )
