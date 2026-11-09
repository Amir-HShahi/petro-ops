"""Errors raised by the Organizational Hierarchy domain."""

from offline_rag.shared_kernel.errors import DomainError


class InvalidLayerDetailLevelError(DomainError):
    """A Layer has a detail level when it must not, or lacks one when it needs one.

    Layer 4 only provides knowledge and receives none; Layers 0 to 3 each receive
    knowledge at one detail level (spec §6.4, registry README).
    """

    code = "ORGANIZATION_INVALID_LAYER_DETAIL_LEVEL"

    def __init__(self, *, layer_index: int, detail_level: str | None) -> None:
        """Create the error for the rejected Layer."""
        if detail_level is None:
            message = (
                f"Layer {layer_index} needs the detail level it receives from the Layer below."
            )
        else:
            message = "Layer 4 only provides knowledge, so it receives no detail level."
        super().__init__(
            message,
            details={"layer_index": layer_index, "detail_level": detail_level},
        )


class ParentNodeRequiredError(DomainError):
    """A Node below Layer 0 has no parent. Only the Layer 0 Node may have none (spec §6.1)."""

    code = "ORGANIZATION_PARENT_NODE_REQUIRED"

    def __init__(self, *, node_id: str, layer_index: int) -> None:
        """Create the error for the Node without a parent."""
        super().__init__(
            f"Node '{node_id}' is in Layer {layer_index}, so it needs a parent Node. "
            "Only the Layer 0 Node has no parent.",
            details={"node_id": node_id, "layer_index": layer_index},
        )


class TopLayerNodeHasParentError(DomainError):
    """A Layer 0 Node was given a parent, but Layer 0 is the top of the hierarchy."""

    code = "ORGANIZATION_TOP_LAYER_NODE_HAS_PARENT"

    def __init__(self, *, node_id: str, parent_node_id: str) -> None:
        """Create the error for the Layer 0 Node with a parent."""
        super().__init__(
            f"Node '{node_id}' is in Layer 0, the top of the hierarchy, so it cannot "
            f"have the parent '{parent_node_id}'.",
            details={"node_id": node_id, "parent_node_id": parent_node_id},
        )


class ParentNodeNotInHigherLayerError(DomainError):
    """A parent Node is not in a higher Layer than its child (spec §6.1)."""

    code = "ORGANIZATION_PARENT_NOT_IN_HIGHER_LAYER"

    def __init__(
        self, *, node_id: str, layer_index: int, parent_node_id: str, parent_layer_index: int
    ) -> None:
        """Create the error for the parent in the wrong Layer."""
        super().__init__(
            f"Node '{node_id}' is in Layer {layer_index}, so its parent must be in a higher "
            f"Layer (a lower number), but '{parent_node_id}' is in Layer {parent_layer_index}.",
            details={
                "node_id": node_id,
                "layer_index": layer_index,
                "parent_node_id": parent_node_id,
                "parent_layer_index": parent_layer_index,
            },
        )


class ParentStructureNotTrackedError(DomainError):
    """A Node was placed under a parent whose inside is outside the system boundary.

    The children of a Node are modelled only when its internal structure is
    tracked (spec §6.1).
    """

    code = "ORGANIZATION_PARENT_STRUCTURE_NOT_TRACKED"

    def __init__(self, *, node_id: str, parent_node_id: str) -> None:
        """Create the error for the child of an untracked Node."""
        super().__init__(
            f"Node '{parent_node_id}' does not track its internal structure, so '{node_id}' "
            "cannot be registered under it. Turn on tracking for the parent first.",
            details={"node_id": node_id, "parent_node_id": parent_node_id},
        )
