"""In-memory fakes of the Organizational Hierarchy ports, for unit tests.

`FakeClock` and `InMemoryEventPublisher` from `tests.fakes.knowledge` fit these
ports too, so they are not repeated here.
"""

from collections.abc import Iterable

from offline_rag.organization.application.errors import LayerNotFoundError, NodeNotFoundError
from offline_rag.organization.domain.layer import Layer
from offline_rag.organization.domain.node import Node
from offline_rag.organization.domain.transfer_detail_level import TransferDetailLevel
from offline_rag.shared_kernel.layer_index import LayerIndex
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

DETAIL_LEVEL_BY_LAYER = {
    0: TransferDetailLevel.TOP_EXECUTIVE,
    1: TransferDetailLevel.MANAGERIAL,
    2: TransferDetailLevel.TECHNICAL_SUMMARY,
    3: TransferDetailLevel.DETAILED_TECHNICAL,
    4: None,
}


def registry_layers() -> list[Layer]:
    """Return the five Layers of `fixtures/registry/layers.csv`."""
    return [
        Layer(
            layer_index=LayerIndex(index),
            name=f"Layer {index}",
            role=f"Role of Layer {index}",
            received_detail_level=detail_level,
        )
        for index, detail_level in DETAIL_LEVEL_BY_LAYER.items()
    ]


class InMemoryNodeRepository:
    """Keeps Nodes in a dict by id."""

    def __init__(self, nodes: Iterable[Node] = ()) -> None:
        self.nodes: dict[NodeIdentifier, Node] = {node.node_id: node for node in nodes}

    def get_by_id(self, node_id: NodeIdentifier) -> Node:
        node = self.find_by_id(node_id)
        if node is None:
            raise NodeNotFoundError(node_id.value)
        return node

    def find_by_id(self, node_id: NodeIdentifier) -> Node | None:
        return self.nodes.get(node_id)

    def find_all(self) -> list[Node]:
        return sorted(
            self.nodes.values(), key=lambda node: (node.layer_index.value, node.node_id.value)
        )

    def add(self, node: Node) -> None:
        self.nodes[node.node_id] = node


class InMemoryLayerRepository:
    """Keeps Layers in a dict by index."""

    def __init__(self, layers: Iterable[Layer]) -> None:
        self.layers = {layer.layer_index: layer for layer in layers}

    def get_by_index(self, layer_index: LayerIndex) -> Layer:
        layer = self.layers.get(layer_index)
        if layer is None:
            raise LayerNotFoundError(layer_index.value)
        return layer

    def find_all(self) -> list[Layer]:
        return sorted(self.layers.values(), key=lambda layer: layer.layer_index.value)
