"""Errors raised by Knowledge Management use cases and the ports they depend on."""

from offline_rag.shared_kernel.errors import NotFoundError
from offline_rag.shared_kernel.node_identifier import NodeIdentifier


class OwnerNodeNotFoundError(NotFoundError):
    """A KnowledgeItem was submitted for a Node that is not in the registry."""

    code = "KNOWLEDGE_OWNER_NODE_NOT_FOUND"

    def __init__(self, node_id: NodeIdentifier) -> None:
        """Create the error for the unknown Node."""
        super().__init__(
            f"Node '{node_id}' is not registered. Register the Node before adding knowledge.",
            details={"node_id": node_id.value},
        )


class KnowledgeItemNotFoundError(NotFoundError):
    """No KnowledgeItem has the requested id."""

    code = "KNOWLEDGE_ITEM_NOT_FOUND"

    def __init__(self, item_id: str) -> None:
        """Create the error for the missing item."""
        super().__init__(
            f"KnowledgeItem '{item_id}' does not exist.",
            details={"item_id": item_id},
        )
