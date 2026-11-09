from datetime import UTC, datetime

import pytest

from offline_rag.organization.domain.errors import (
    ParentNodeNotInHigherLayerError,
    ParentNodeRequiredError,
    ParentStructureNotTrackedError,
    TopLayerNodeHasParentError,
)
from offline_rag.organization.domain.events import NodeRegistered
from offline_rag.organization.domain.node import Node
from offline_rag.shared_kernel.confidentiality_level import ConfidentialityLevel
from offline_rag.shared_kernel.layer_index import LayerIndex
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

REGISTERED_AT = datetime(2026, 11, 9, 10, 0, tzinfo=UTC)


def _node(
    node_id: str,
    layer: int,
    parent_node_id: str | None,
    *,
    is_tracked: bool = True,
) -> Node:
    return Node(
        node_id=NodeIdentifier(node_id),
        name=node_id.replace("_", " ").title(),
        layer_index=LayerIndex(layer),
        parent_node_id=NodeIdentifier(parent_node_id) if parent_node_id else None,
        activity_area="offshore production",
        reporting_rule="weekly",
        confidentiality=ConfidentialityLevel.INTERNAL,
        is_internal_structure_tracked=is_tracked,
    )


def _register(node_id: str, layer: int, parent: Node | None, *, is_tracked: bool = False) -> Node:
    return Node.register(
        node_id=NodeIdentifier(node_id),
        name="SP-12 Inspection Team",
        layer_index=LayerIndex(layer),
        parent=parent,
        activity_area="inspection and corrosion monitoring",
        reporting_rule="per shift",
        confidentiality=ConfidentialityLevel.INTERNAL,
        is_internal_structure_tracked=is_tracked,
        registered_at=REGISTERED_AT,
    )


PLATFORM_SP12 = _node("platform_sp12", 2, "region_south_operator")


def test_node_is_registered_under_its_parent_when_parent_is_in_a_higher_layer():
    node = _register("sp12_inspection_team", 3, PLATFORM_SP12)

    assert node.node_id == NodeIdentifier("sp12_inspection_team")
    assert node.layer_index == LayerIndex(3)
    assert node.parent_node_id == NodeIdentifier("platform_sp12")
    assert node.reporting_rule == "per shift"
    assert node.confidentiality == ConfidentialityLevel.INTERNAL
    assert not node.is_internal_structure_tracked


def test_node_records_registered_event_when_registered():
    node = _register("sp12_inspection_team", 3, PLATFORM_SP12)

    assert node.pull_events() == (
        NodeRegistered(
            occurred_at=REGISTERED_AT,
            node_id=NodeIdentifier("sp12_inspection_team"),
            layer_index=LayerIndex(3),
            parent_node_id=NodeIdentifier("platform_sp12"),
        ),
    )
    assert node.pull_events() == ()


def test_top_layer_node_is_registered_when_it_has_no_parent():
    node = _register("national_oil_company", 0, None, is_tracked=True)

    assert node.parent_node_id is None
    assert node.pull_events()[0] == NodeRegistered(
        occurred_at=REGISTERED_AT,
        node_id=NodeIdentifier("national_oil_company"),
        layer_index=LayerIndex(0),
        parent_node_id=None,
    )


def test_node_is_registered_when_its_parent_skips_layers():
    operator = _node("region_south_operator", 1, "national_oil_company")

    node = _register("region_south_hse_team", 3, operator)

    assert node.parent_node_id == NodeIdentifier("region_south_operator")


@pytest.mark.parametrize("layer", [1, 2, 3, 4])
def test_node_is_rejected_when_below_layer_zero_without_parent(layer: int):
    with pytest.raises(ParentNodeRequiredError) as caught:
        _register("orphan_team", layer, None)

    assert caught.value.code == "ORGANIZATION_PARENT_NODE_REQUIRED"
    assert caught.value.details == {"node_id": "orphan_team", "layer_index": layer}


def test_node_is_rejected_when_in_layer_zero_with_parent():
    with pytest.raises(TopLayerNodeHasParentError) as caught:
        _register("national_oil_company", 0, PLATFORM_SP12)

    assert caught.value.code == "ORGANIZATION_TOP_LAYER_NODE_HAS_PARENT"
    assert caught.value.details == {
        "node_id": "national_oil_company",
        "parent_node_id": "platform_sp12",
    }


@pytest.mark.parametrize("child_layer", [1, 2])
def test_node_is_rejected_when_parent_is_not_in_a_higher_layer(child_layer: int):
    with pytest.raises(ParentNodeNotInHigherLayerError) as caught:
        _register("misplaced_unit", child_layer, PLATFORM_SP12)

    assert caught.value.code == "ORGANIZATION_PARENT_NOT_IN_HIGHER_LAYER"
    assert caught.value.details == {
        "node_id": "misplaced_unit",
        "layer_index": child_layer,
        "parent_node_id": "platform_sp12",
        "parent_layer_index": 2,
    }


def test_node_is_rejected_when_parent_does_not_track_its_structure():
    platform_sp14 = _node("platform_sp14", 2, "region_south_operator", is_tracked=False)

    with pytest.raises(ParentStructureNotTrackedError) as caught:
        _register("sp14_maintenance_team", 3, platform_sp14)

    assert caught.value.code == "ORGANIZATION_PARENT_STRUCTURE_NOT_TRACKED"
    assert caught.value.details == {
        "node_id": "sp14_maintenance_team",
        "parent_node_id": "platform_sp14",
    }


def test_rebuilt_node_records_no_events_when_loaded():
    assert PLATFORM_SP12.pull_events() == ()


def test_rebuilt_node_is_rejected_when_below_layer_zero_without_parent():
    with pytest.raises(ParentNodeRequiredError):
        _node("platform_sp12", 2, None)


def test_nodes_are_equal_when_they_share_an_id():
    same = _node("platform_sp12", 2, "region_south_operator", is_tracked=False)

    assert same == PLATFORM_SP12
    assert hash(same) == hash(PLATFORM_SP12)
    assert same != _node("platform_sp14", 2, "region_south_operator")
