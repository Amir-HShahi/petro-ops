from tests.fakes.organization import InMemoryNodeRepository

from offline_rag.organization.application.node_queries import NodeQueries
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


def _queries() -> NodeQueries:
    return NodeQueries(
        node_repository=InMemoryNodeRepository(
            [
                _node("national_oil_company", 0, None),
                _node("affiliated_company", 1, "national_oil_company"),
                _node("platform_sp12", 2, "affiliated_company"),
            ]
        )
    )


def test_node_is_registered_when_the_repository_holds_it():
    assert _queries().is_registered(NodeIdentifier("platform_sp12"))


def test_node_is_not_registered_when_the_repository_lacks_it():
    assert not _queries().is_registered(NodeIdentifier("platform_sp99"))


def test_node_ids_are_sorted_by_id_when_listed():
    assert [node_id.value for node_id in _queries().list_node_ids()] == [
        "affiliated_company",
        "national_oil_company",
        "platform_sp12",
    ]


def test_no_node_ids_are_listed_when_none_is_registered():
    assert NodeQueries(node_repository=InMemoryNodeRepository()).list_node_ids() == []
