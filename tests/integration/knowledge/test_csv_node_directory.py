from pathlib import Path

import pytest

from offline_rag.knowledge.infrastructure.csv_node_directory import CsvNodeDirectory
from offline_rag.knowledge.infrastructure.errors import NodeRegistryUnavailableError
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

pytestmark = pytest.mark.integration

REGISTRY_PATH = Path(__file__).parents[3] / "fixtures" / "registry" / "nodes.csv"


@pytest.mark.parametrize(
    "node_id", ["national_oil_company", "platform_sp12", "sp12_inspection_team"]
)
def test_registered_node_is_found_when_registry_lists_it(node_id: str):
    assert CsvNodeDirectory(REGISTRY_PATH).has_node(NodeIdentifier(node_id))


def test_unknown_node_is_not_found_when_registry_does_not_list_it():
    assert not CsvNodeDirectory(REGISTRY_PATH).has_node(NodeIdentifier("platform_sp99"))


def test_registry_error_is_raised_when_file_is_missing(tmp_path: Path):
    directory = CsvNodeDirectory(tmp_path / "missing.csv")

    with pytest.raises(NodeRegistryUnavailableError) as caught:
        directory.has_node(NodeIdentifier("platform_sp12"))

    assert caught.value.code == "KNOWLEDGE_NODE_REGISTRY_UNAVAILABLE"


@pytest.mark.parametrize(
    "registry_text",
    ["name,layer_index\nPlatform SP-12,2\n", "node_id,name\n,Nameless Node\n"],
)
def test_registry_error_is_raised_when_file_content_is_invalid(tmp_path: Path, registry_text: str):
    registry = tmp_path / "nodes.csv"
    registry.write_text(registry_text)

    with pytest.raises(NodeRegistryUnavailableError):
        CsvNodeDirectory(registry).has_node(NodeIdentifier("platform_sp12"))
