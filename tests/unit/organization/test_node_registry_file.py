from pathlib import Path

import pytest

from offline_rag.organization.interface.errors import (
    NodeRegistryFileInvalidError,
    NodeRegistryFileNotReadableError,
)
from offline_rag.organization.interface.node_registry_file import read_node_registry
from offline_rag.shared_kernel.confidentiality_level import ConfidentialityLevel
from offline_rag.shared_kernel.layer_index import LayerIndex
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

FIXTURE_REGISTRY = Path(__file__).parents[3] / "fixtures" / "registry" / "nodes.csv"
HEADER = (
    "node_id,name,layer_index,parent_node_id,activity_area,reporting_rule,"
    "confidentiality,is_internal_structure_tracked\n"
)


def _registry(tmp_path: Path, *rows: str, header: str = HEADER) -> Path:
    path = tmp_path / "nodes.csv"
    path.write_text(header + "".join(f"{row}\n" for row in rows), encoding="utf-8")
    return path


def test_fixture_registry_is_read_top_layer_first_when_loaded():
    commands = read_node_registry(FIXTURE_REGISTRY)

    assert len(commands) == 9
    assert [command.layer_index.value for command in commands] == sorted(
        command.layer_index.value for command in commands
    )
    assert commands[0].node_id == NodeIdentifier("national_oil_company")
    assert commands[0].parent_node_id is None


def test_row_becomes_a_register_command_when_valid(tmp_path: Path):
    path = _registry(
        tmp_path,
        "sp12_inspection_team,SP-12 Inspection Team,3,platform_sp12,inspection,per shift,"
        "confidential,FALSE",
    )

    [command] = read_node_registry(path)

    assert command.node_id == NodeIdentifier("sp12_inspection_team")
    assert command.name == "SP-12 Inspection Team"
    assert command.layer_index == LayerIndex(3)
    assert command.parent_node_id == NodeIdentifier("platform_sp12")
    assert command.reporting_rule == "per shift"
    assert command.confidentiality == ConfidentialityLevel.CONFIDENTIAL
    assert command.is_internal_structure_tracked is False


@pytest.mark.parametrize(
    ("row", "column", "value"),
    [
        ("team,Team,7,parent,area,weekly,internal,false", "layer_index", "7"),
        ("team,Team,three,parent,area,weekly,internal,false", "layer_index", "three"),
        ("team,Team,3,parent,area,weekly,secret,false", "confidentiality", "secret"),
        ("team,Team,3,parent,area,weekly,internal,maybe", "is_internal_structure_tracked", "maybe"),
        (" ,Team,3,parent,area,weekly,internal,false", "node_id", ""),
    ],
)
def test_row_is_rejected_when_a_value_is_wrong(tmp_path: Path, row: str, column: str, value: str):
    with pytest.raises(NodeRegistryFileInvalidError) as caught:
        read_node_registry(_registry(tmp_path, row))

    assert caught.value.code == "ORGANIZATION_NODE_REGISTRY_FILE_INVALID"
    assert caught.value.details == {"row_number": 1, "column": column, "value": value}


def test_row_is_rejected_when_a_column_is_missing(tmp_path: Path):
    path = _registry(tmp_path, "team,Team", header="node_id,name\n")

    with pytest.raises(NodeRegistryFileInvalidError) as caught:
        read_node_registry(path)

    assert caught.value.details["value"] is None


def test_file_is_rejected_when_it_does_not_exist(tmp_path: Path):
    with pytest.raises(NodeRegistryFileNotReadableError) as caught:
        read_node_registry(tmp_path / "missing.csv")

    assert caught.value.code == "ORGANIZATION_NODE_REGISTRY_FILE_NOT_READABLE"
    assert caught.value.details == {"file_name": "missing.csv"}
