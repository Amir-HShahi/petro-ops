from tests.fakes.organization import (
    InMemoryLayerRepository,
    InMemoryNodeRepository,
    registry_layers,
)

from offline_rag.organization.application.hierarchy_queries import HierarchyQueries
from offline_rag.organization.domain.node import Node
from offline_rag.shared_kernel.confidentiality_level import ConfidentialityLevel
from offline_rag.shared_kernel.layer_index import LayerIndex
from offline_rag.shared_kernel.node_identifier import NodeIdentifier


def _node(node_id: str, layer: int, parent: str | None) -> Node:
    return Node(
        node_id=NodeIdentifier(node_id),
        name=node_id,
        layer_index=LayerIndex(layer),
        parent_node_id=NodeIdentifier(parent) if parent else None,
        activity_area="offshore production",
        reporting_rule="weekly",
        confidentiality=ConfidentialityLevel.INTERNAL,
        is_internal_structure_tracked=True,
    )


def test_layers_are_listed_from_layer_0_when_asked():
    queries = HierarchyQueries(
        layer_repository=InMemoryLayerRepository(reversed(registry_layers())),
        node_repository=InMemoryNodeRepository(),
    )

    assert [layer.layer_index.value for layer in queries.list_layers()] == [0, 1, 2, 3, 4]


def test_nodes_are_listed_from_the_top_layer_down_when_asked():
    nodes = InMemoryNodeRepository(
        [_node("team_b", 2, "unit_a"), _node("unit_a", 1, "root"), _node("root", 0, None)]
    )
    queries = HierarchyQueries(
        layer_repository=InMemoryLayerRepository(registry_layers()), node_repository=nodes
    )

    assert [node.node_id.value for node in queries.list_nodes()] == ["root", "unit_a", "team_b"]
