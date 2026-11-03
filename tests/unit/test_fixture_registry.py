import csv
from pathlib import Path

FIXTURES_DIR = Path(__file__).parents[2] / "fixtures"
LAYERS_PATH = FIXTURES_DIR / "registry" / "layers.csv"
NODES_PATH = FIXTURES_DIR / "registry" / "nodes.csv"
MANIFEST_PATH = FIXTURES_DIR / "docs" / "manifest.csv"
DETAIL_LEVELS = {"top_executive", "managerial", "technical_summary", "detailed_technical", ""}
CONFIDENTIALITY_LEVELS = {"public", "internal", "confidential"}


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as registry:
        return list(csv.DictReader(registry))


def _layer_by_node() -> dict[str, int]:
    return {node["node_id"]: int(node["layer_index"]) for node in _rows(NODES_PATH)}


def test_layers_cover_zero_to_four_when_loaded():
    assert [int(layer["layer_index"]) for layer in _rows(LAYERS_PATH)] == [0, 1, 2, 3, 4]


def test_layers_use_known_detail_levels_when_loaded():
    assert {layer["received_detail_level"] for layer in _rows(LAYERS_PATH)} <= DETAIL_LEVELS


def test_node_ids_are_unique_when_loaded():
    node_ids = [node["node_id"] for node in _rows(NODES_PATH)]

    assert len(node_ids) == len(set(node_ids))


def test_nodes_belong_to_known_layers_when_loaded():
    layer_indexes = {int(layer["layer_index"]) for layer in _rows(LAYERS_PATH)}

    assert set(_layer_by_node().values()) <= layer_indexes


def test_only_layer_zero_nodes_have_no_parent_when_loaded():
    for node in _rows(NODES_PATH):
        assert (node["parent_node_id"] == "") == (node["layer_index"] == "0"), node["node_id"]


def test_parent_is_in_a_higher_layer_when_set():
    layer_by_node = _layer_by_node()

    for node in _rows(NODES_PATH):
        if node["parent_node_id"]:
            assert layer_by_node[node["parent_node_id"]] < int(node["layer_index"]), node["node_id"]


def test_nodes_with_children_track_internal_structure_when_loaded():
    nodes = _rows(NODES_PATH)
    parents = {node["parent_node_id"] for node in nodes} - {""}

    for node in nodes:
        assert node["is_internal_structure_tracked"] in {"true", "false"}, node["node_id"]
        if node["node_id"] in parents:
            assert node["is_internal_structure_tracked"] == "true", node["node_id"]


def test_nodes_use_known_confidentiality_levels_when_loaded():
    assert {node["confidentiality"] for node in _rows(NODES_PATH)} <= CONFIDENTIALITY_LEVELS


def test_manifest_nodes_match_registry_layers_when_compared():
    layer_by_node = _layer_by_node()

    for row in _rows(MANIFEST_PATH):
        assert layer_by_node.get(row["node"]) == int(row["layer"]), row["id"]
