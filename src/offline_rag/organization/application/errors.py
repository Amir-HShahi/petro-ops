"""Errors raised by the Organizational Hierarchy use cases and repositories."""

from offline_rag.shared_kernel.errors import DomainError, NotFoundError


class NodeNotFoundError(NotFoundError):
    """No Node has the requested id."""

    code = "ORGANIZATION_NODE_NOT_FOUND"

    def __init__(self, node_id: str) -> None:
        """Create the error for the missing Node."""
        super().__init__(
            f"Node '{node_id}' is not registered.",
            details={"node_id": node_id},
        )


class LayerNotFoundError(NotFoundError):
    """No Layer has the requested index; the Layers were not loaded."""

    code = "ORGANIZATION_LAYER_NOT_FOUND"

    def __init__(self, layer_index: int) -> None:
        """Create the error for the missing Layer."""
        super().__init__(
            f"Layer {layer_index} is not in the registry. Run the database migrations, "
            "which load the five Layers.",
            details={"layer_index": layer_index},
        )


class NodeAlreadyRegisteredError(DomainError):
    """A Node with the same id is already registered, and a Node id never changes."""

    code = "ORGANIZATION_NODE_ALREADY_REGISTERED"

    def __init__(self, node_id: str) -> None:
        """Create the error for the taken id."""
        super().__init__(
            f"Node '{node_id}' is already registered. Pick another id.",
            details={"node_id": node_id},
        )


class TopLayerNodeAlreadyRegisteredError(DomainError):
    """A second Node was sent to Layer 0, which has one Node at the top of the hierarchy."""

    code = "ORGANIZATION_TOP_LAYER_NODE_ALREADY_REGISTERED"

    def __init__(self, *, node_id: str, top_node_id: str) -> None:
        """Create the error for the second top Node."""
        super().__init__(
            f"Layer 0 already has the Node '{top_node_id}', so '{node_id}' cannot join it. "
            "Register it in a lower Layer under an existing Node.",
            details={"node_id": node_id, "top_node_id": top_node_id},
        )
