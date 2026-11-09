import pytest
from tests.fakes.knowledge import FakeClock, InMemoryEventPublisher
from tests.fakes.organization import (
    InMemoryLayerRepository,
    InMemoryNodeRepository,
    registry_layers,
)

from offline_rag.organization.application.commands import RegisterNode
from offline_rag.organization.application.errors import (
    LayerNotFoundError,
    NodeAlreadyRegisteredError,
    NodeNotFoundError,
    TopLayerNodeAlreadyRegisteredError,
)
from offline_rag.organization.application.register_node import RegisterNodeHandler
from offline_rag.organization.domain.errors import (
    ParentNodeNotInHigherLayerError,
    ParentStructureNotTrackedError,
)
from offline_rag.organization.domain.events import NodeRegistered
from offline_rag.organization.domain.node import Node
from offline_rag.shared_kernel.confidentiality_level import ConfidentialityLevel
from offline_rag.shared_kernel.layer_index import LayerIndex
from offline_rag.shared_kernel.node_identifier import NodeIdentifier


def _command(
    node_id: str,
    layer: int,
    parent: str | None,
    *,
    is_tracked: bool = False,
) -> RegisterNode:
    return RegisterNode(
        node_id=NodeIdentifier(node_id),
        name=node_id.replace("_", " ").title(),
        layer_index=LayerIndex(layer),
        parent_node_id=NodeIdentifier(parent) if parent else None,
        activity_area="offshore production",
        reporting_rule="weekly",
        confidentiality=ConfidentialityLevel.INTERNAL,
        is_internal_structure_tracked=is_tracked,
    )


@pytest.fixture
def nodes() -> InMemoryNodeRepository:
    return InMemoryNodeRepository()


@pytest.fixture
def publisher() -> InMemoryEventPublisher:
    return InMemoryEventPublisher()


@pytest.fixture
def handler(
    nodes: InMemoryNodeRepository, publisher: InMemoryEventPublisher
) -> RegisterNodeHandler:
    return RegisterNodeHandler(
        node_repository=nodes,
        layer_repository=InMemoryLayerRepository(registry_layers()),
        clock=FakeClock(),
        event_publisher=publisher,
    )


def _register_top_and_operator(handler: RegisterNodeHandler) -> None:
    handler.register(_command("national_oil_company", 0, None, is_tracked=True))
    handler.register(_command("region_south_operator", 1, "national_oil_company", is_tracked=True))


def test_node_is_stored_when_registered_under_a_registered_parent(
    handler: RegisterNodeHandler, nodes: InMemoryNodeRepository
):
    _register_top_and_operator(handler)

    node = handler.register(_command("platform_sp12", 2, "region_south_operator"))

    assert nodes.get_by_id(NodeIdentifier("platform_sp12")) is node
    assert node.parent_node_id == NodeIdentifier("region_south_operator")


def test_registered_event_is_published_when_node_is_registered(
    handler: RegisterNodeHandler, publisher: InMemoryEventPublisher
):
    handler.register(_command("national_oil_company", 0, None, is_tracked=True))

    assert [type(event) for event in publisher.events] == [NodeRegistered]


def test_whole_fixture_hierarchy_registers_when_sent_top_down(
    handler: RegisterNodeHandler, nodes: InMemoryNodeRepository
):
    _register_top_and_operator(handler)
    handler.register(_command("platform_sp12", 2, "region_south_operator", is_tracked=True))
    handler.register(_command("sp12_inspection_team", 3, "platform_sp12"))
    handler.register(_command("region_south_archive", 4, "region_south_operator"))

    assert [node.node_id.value for node in nodes.find_all()] == [
        "national_oil_company",
        "region_south_operator",
        "platform_sp12",
        "sp12_inspection_team",
        "region_south_archive",
    ]


def test_node_is_rejected_when_its_id_is_taken(
    handler: RegisterNodeHandler, publisher: InMemoryEventPublisher
):
    handler.register(_command("national_oil_company", 0, None, is_tracked=True))

    with pytest.raises(NodeAlreadyRegisteredError) as caught:
        handler.register(_command("national_oil_company", 0, None))

    assert caught.value.code == "ORGANIZATION_NODE_ALREADY_REGISTERED"
    assert caught.value.details == {"node_id": "national_oil_company"}
    assert len(publisher.events) == 1


def test_node_is_rejected_when_layer_zero_already_has_a_node(
    handler: RegisterNodeHandler, nodes: InMemoryNodeRepository
):
    handler.register(_command("national_oil_company", 0, None, is_tracked=True))

    with pytest.raises(TopLayerNodeAlreadyRegisteredError) as caught:
        handler.register(_command("second_ministry", 0, None))

    assert caught.value.code == "ORGANIZATION_TOP_LAYER_NODE_ALREADY_REGISTERED"
    assert caught.value.details == {
        "node_id": "second_ministry",
        "top_node_id": "national_oil_company",
    }
    assert nodes.find_by_id(NodeIdentifier("second_ministry")) is None


def test_node_is_rejected_when_its_parent_is_not_registered(
    handler: RegisterNodeHandler, nodes: InMemoryNodeRepository
):
    with pytest.raises(NodeNotFoundError) as caught:
        handler.register(_command("platform_sp12", 2, "region_south_operator"))

    assert caught.value.code == "ORGANIZATION_NODE_NOT_FOUND"
    assert caught.value.details == {"node_id": "region_south_operator"}
    assert nodes.nodes == {}


def test_node_is_rejected_when_its_layer_is_not_loaded(nodes: InMemoryNodeRepository):
    handler = RegisterNodeHandler(
        node_repository=nodes,
        layer_repository=InMemoryLayerRepository([]),
        clock=FakeClock(),
        event_publisher=InMemoryEventPublisher(),
    )

    with pytest.raises(LayerNotFoundError) as caught:
        handler.register(_command("national_oil_company", 0, None))

    assert caught.value.code == "ORGANIZATION_LAYER_NOT_FOUND"
    assert caught.value.details == {"layer_index": 0}


@pytest.mark.parametrize(
    ("command", "error"),
    [
        (_command("misplaced_unit", 1, "region_south_operator"), ParentNodeNotInHigherLayerError),
        (_command("sp14_team", 3, "platform_sp14"), ParentStructureNotTrackedError),
    ],
)
def test_nothing_is_stored_or_published_when_parent_cannot_take_the_node(
    handler: RegisterNodeHandler,
    nodes: InMemoryNodeRepository,
    publisher: InMemoryEventPublisher,
    command: RegisterNode,
    error: type[Exception],
):
    _register_top_and_operator(handler)
    handler.register(_command("platform_sp14", 2, "region_south_operator", is_tracked=False))
    stored_before = dict(nodes.nodes)
    published_before = list(publisher.events)

    with pytest.raises(error):
        handler.register(command)

    assert nodes.nodes == stored_before
    assert publisher.events == published_before


def test_stored_parent_is_used_when_node_is_registered(nodes: InMemoryNodeRepository):
    parent = Node(
        node_id=NodeIdentifier("region_south_operator"),
        name="Region South Gas Operator",
        layer_index=LayerIndex(1),
        parent_node_id=NodeIdentifier("national_oil_company"),
        activity_area="South Field gas production",
        reporting_rule="monthly",
        confidentiality=ConfidentialityLevel.INTERNAL,
        is_internal_structure_tracked=True,
    )
    nodes.add(parent)
    handler = RegisterNodeHandler(
        node_repository=nodes,
        layer_repository=InMemoryLayerRepository(registry_layers()),
        clock=FakeClock(),
        event_publisher=InMemoryEventPublisher(),
    )

    node = handler.register(_command("region_south_hse_team", 3, "region_south_operator"))

    assert node.parent_node_id == parent.node_id
