"""Read-only queries on the Layer registry and the Node hierarchy, for the API and the page."""

from offline_rag.organization.application.ports import LayerRepository, NodeRepository
from offline_rag.organization.domain.layer import Layer
from offline_rag.organization.domain.node import Node


class HierarchyQueries:
    """Answers what the Layers require and which Nodes make up the hierarchy."""

    def __init__(
        self, *, layer_repository: LayerRepository, node_repository: NodeRepository
    ) -> None:
        """Create the queries over the Layer and Node stores."""
        self._layer_repository = layer_repository
        self._node_repository = node_repository

    def list_layers(self) -> list[Layer]:
        """Return the five Layers with their detail levels and transfer rules, Layer 0 first."""
        return self._layer_repository.find_all()

    def list_nodes(self) -> list[Node]:
        """Return every Node, from the top Layer down, then by id."""
        return self._node_repository.find_all()
