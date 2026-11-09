import json
from pathlib import Path

import pytest
from tests.fakes.knowledge import FakeClock, InMemoryEventPublisher

from offline_rag.organization.application.errors import (
    LayerNotFoundError,
    NodeAlreadyRegisteredError,
    NodeNotFoundError,
)
from offline_rag.organization.application.register_node import RegisterNodeHandler
from offline_rag.organization.domain.node import Node
from offline_rag.organization.domain.transfer_detail_level import TransferDetailLevel
from offline_rag.organization.infrastructure.errors import OrganizationStorageError
from offline_rag.organization.infrastructure.postgres_database import PostgresDatabase
from offline_rag.organization.infrastructure.postgres_layer_repository import (
    PostgresLayerRepository,
)
from offline_rag.organization.infrastructure.postgres_node_repository import (
    PostgresNodeRepository,
)
from offline_rag.organization.interface import cli
from offline_rag.organization.interface.node_registry_file import read_node_registry
from offline_rag.settings import Settings
from offline_rag.shared_kernel.confidentiality_level import ConfidentialityLevel
from offline_rag.shared_kernel.layer_index import LayerIndex
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

pytestmark = pytest.mark.integration

FIXTURE_REGISTRY = Path(__file__).parents[3] / "fixtures" / "registry" / "nodes.csv"


def _handler(database: PostgresDatabase) -> RegisterNodeHandler:
    return RegisterNodeHandler(
        node_repository=PostgresNodeRepository(database),
        layer_repository=PostgresLayerRepository(database),
        clock=FakeClock(),
        event_publisher=InMemoryEventPublisher(),
    )


def _top_node(node_id: str = "national_oil_company") -> Node:
    return Node(
        node_id=NodeIdentifier(node_id),
        name="National Oil Company",
        layer_index=LayerIndex(0),
        parent_node_id=None,
        activity_area="national strategy and oversight",
        reporting_rule="quarterly",
        confidentiality=ConfidentialityLevel.INTERNAL,
        is_internal_structure_tracked=True,
    )


def test_migration_loads_the_five_layers_when_applied(database: PostgresDatabase):
    layers = PostgresLayerRepository(database).find_all()

    assert [layer.layer_index.value for layer in layers] == [0, 1, 2, 3, 4]
    assert [layer.received_detail_level for layer in layers] == [
        TransferDetailLevel.TOP_EXECUTIVE,
        TransferDetailLevel.MANAGERIAL,
        TransferDetailLevel.TECHNICAL_SUMMARY,
        TransferDetailLevel.DETAILED_TECHNICAL,
        None,
    ]
    assert layers[1].name == "Parent organizations"


def test_layer_is_read_by_index_when_present(database: PostgresDatabase):
    layer = PostgresLayerRepository(database).get_by_index(LayerIndex(4))

    assert not layer.receives_transfer_package


def test_layer_is_not_found_when_its_row_is_gone(database: PostgresDatabase):
    with database.transaction("test") as connection:
        connection.execute("DELETE FROM layer WHERE layer_index = 4")

    with pytest.raises(LayerNotFoundError):
        PostgresLayerRepository(database).get_by_index(LayerIndex(4))


def test_node_round_trips_when_stored(database: PostgresDatabase):
    repository = PostgresNodeRepository(database)
    repository.add(_top_node())
    child = Node(
        node_id=NodeIdentifier("region_south_operator"),
        name="Region South Gas Operator",
        layer_index=LayerIndex(1),
        parent_node_id=NodeIdentifier("national_oil_company"),
        activity_area="South Field gas production",
        reporting_rule="monthly",
        confidentiality=ConfidentialityLevel.CONFIDENTIAL,
        is_internal_structure_tracked=False,
    )
    repository.add(child)

    loaded = repository.get_by_id(NodeIdentifier("region_south_operator"))

    assert loaded == child
    assert loaded.name == "Region South Gas Operator"
    assert loaded.layer_index == LayerIndex(1)
    assert loaded.parent_node_id == NodeIdentifier("national_oil_company")
    assert loaded.activity_area == "South Field gas production"
    assert loaded.reporting_rule == "monthly"
    assert loaded.confidentiality == ConfidentialityLevel.CONFIDENTIAL
    assert loaded.is_internal_structure_tracked is False


def test_node_is_not_found_when_missing(database: PostgresDatabase):
    repository = PostgresNodeRepository(database)

    assert repository.find_by_id(NodeIdentifier("platform_sp12")) is None
    with pytest.raises(NodeNotFoundError):
        repository.get_by_id(NodeIdentifier("platform_sp12"))


def test_database_refuses_a_second_top_node_when_added_directly(database: PostgresDatabase):
    repository = PostgresNodeRepository(database)
    repository.add(_top_node())

    with pytest.raises(OrganizationStorageError):
        repository.add(_top_node("second_ministry"))


def test_fixture_registry_registers_every_node_when_imported(database: PostgresDatabase):
    handler = _handler(database)

    for command in read_node_registry(FIXTURE_REGISTRY):
        handler.register(command)

    nodes = PostgresNodeRepository(database).find_all()
    assert len(nodes) == 9
    assert [node.layer_index.value for node in nodes] == [0, 1, 2, 2, 3, 3, 3, 3, 4]
    assert nodes[0].node_id == NodeIdentifier("national_oil_company")


def test_second_import_changes_nothing_when_nodes_exist(database: PostgresDatabase):
    handler = _handler(database)
    commands = read_node_registry(FIXTURE_REGISTRY)
    for command in commands:
        handler.register(command)

    with pytest.raises(NodeAlreadyRegisteredError):
        handler.register(commands[0])
    assert len(PostgresNodeRepository(database).find_all()) == 9


def test_cli_imports_the_registry_once_when_run_twice(
    postgres_url: str, capsys: pytest.CaptureFixture[str]
):
    settings = Settings(database_url=postgres_url)

    assert cli.main(["import-nodes"], settings=settings) == cli.EXIT_OK
    first = json.loads(capsys.readouterr().out)
    assert cli.main(["import-nodes"], settings=settings) == cli.EXIT_OK
    second = json.loads(capsys.readouterr().out)

    assert len(first["registered"]) == 9
    assert first["already_registered"] == []
    assert second == {"registered": [], "already_registered": first["registered"]}


def test_cli_reports_problem_details_when_parent_is_unknown(
    postgres_url: str, capsys: pytest.CaptureFixture[str]
):
    settings = Settings(database_url=postgres_url)

    exit_code = cli.main(
        [
            "register-node",
            "platform_sp12",
            "--name",
            "Platform SP-12",
            "--layer",
            "2",
            "--parent",
            "region_south_operator",
            "--activity-area",
            "offshore production",
            "--reporting-rule",
            "weekly",
        ],
        settings=settings,
    )

    problem = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert exit_code == cli.EXIT_FAILED
    assert problem["type"] == "ORGANIZATION_NODE_NOT_FOUND"
    assert problem["status"] == 404
