import pytest
from tests.fakes.organization import InMemoryNodeRepository

from offline_rag.knowledge.infrastructure.errors import NodeRegistryUnavailableError
from offline_rag.knowledge.infrastructure.organization_node_directory import (
    OrganizationNodeDirectory,
)
from offline_rag.organization.application.node_queries import NodeQueries
from offline_rag.organization.domain.node import Node
from offline_rag.organization.infrastructure.errors import OrganizationStorageError
from offline_rag.shared_kernel.confidentiality_level import ConfidentialityLevel
from offline_rag.shared_kernel.layer_index import LayerIndex
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

TOP_NODE = Node(
    node_id=NodeIdentifier("national_oil_company"),
    name="National Oil Company",
    layer_index=LayerIndex(0),
    parent_node_id=None,
    activity_area="national strategy and oversight",
    reporting_rule="quarterly",
    confidentiality=ConfidentialityLevel.INTERNAL,
    is_internal_structure_tracked=True,
)


class _UnreachableNodeRepository(InMemoryNodeRepository):
    def find_by_id(self, node_id: NodeIdentifier) -> Node | None:
        operation = "find_by_id"
        raise OrganizationStorageError(operation)

    def find_all(self) -> list[Node]:
        operation = "find_all"
        raise OrganizationStorageError(operation)


def _directory(repository: InMemoryNodeRepository) -> OrganizationNodeDirectory:
    return OrganizationNodeDirectory(NodeQueries(node_repository=repository))


def test_node_is_found_when_organization_registered_it():
    directory = _directory(InMemoryNodeRepository([TOP_NODE]))

    assert directory.has_node(NodeIdentifier("national_oil_company"))
    assert not directory.has_node(NodeIdentifier("platform_sp99"))


def test_node_ids_come_from_organization_when_listed():
    directory = _directory(InMemoryNodeRepository([TOP_NODE]))

    assert directory.list_node_ids() == [NodeIdentifier("national_oil_company")]


def test_lookup_fails_with_a_knowledge_error_when_organization_storage_is_down():
    with pytest.raises(NodeRegistryUnavailableError) as caught:
        _directory(_UnreachableNodeRepository()).has_node(NodeIdentifier("platform_sp12"))

    assert caught.value.code == "KNOWLEDGE_NODE_REGISTRY_UNAVAILABLE"
    assert isinstance(caught.value.__cause__, OrganizationStorageError)


def test_listing_fails_with_a_knowledge_error_when_organization_storage_is_down():
    with pytest.raises(NodeRegistryUnavailableError):
        _directory(_UnreachableNodeRepository()).list_node_ids()
