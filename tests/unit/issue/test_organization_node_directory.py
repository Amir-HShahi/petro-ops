import pytest
from tests.fakes.organization import InMemoryNodeRepository

from offline_rag.issue.infrastructure.errors import NodeRegistryUnavailableError
from offline_rag.issue.infrastructure.organization_node_directory import (
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


def test_node_is_found_only_when_organization_registered_it():
    directory = OrganizationNodeDirectory(
        NodeQueries(node_repository=InMemoryNodeRepository([TOP_NODE]))
    )

    assert directory.has_node(NodeIdentifier("national_oil_company"))
    assert not directory.has_node(NodeIdentifier("platform_sp99"))


def test_lookup_fails_with_an_issue_error_when_organization_storage_is_down():
    directory = OrganizationNodeDirectory(NodeQueries(node_repository=_UnreachableNodeRepository()))

    with pytest.raises(NodeRegistryUnavailableError) as caught:
        directory.has_node(NodeIdentifier("platform_sp12"))

    assert caught.value.code == "ISSUE_NODE_REGISTRY_UNAVAILABLE"
    assert isinstance(caught.value.__cause__, OrganizationStorageError)
