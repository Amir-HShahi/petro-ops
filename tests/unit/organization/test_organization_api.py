import pytest
from fastapi.testclient import TestClient
from tests.fakes.knowledge import (
    FakeClock,
    FakeIngestionQueueMonitor,
    InMemoryEventPublisher,
    InMemoryExtractedContentRepository,
    InMemoryKnowledgeChunkRepository,
    InMemoryKnowledgeIngestionRepository,
    InMemoryKnowledgeItemRepository,
)
from tests.fakes.knowledge_api import NOW, build_api_client
from tests.fakes.organization import (
    InMemoryLayerRepository,
    InMemoryNodeRepository,
    registry_layers,
)

from offline_rag.organization.application.define_transfer_rule import DefineTransferRuleHandler
from offline_rag.organization.application.hierarchy_queries import HierarchyQueries
from offline_rag.organization.application.register_node import RegisterNodeHandler
from offline_rag.organization.interface.api import create_organization_router

RULE = {
    "received_detail_level": "managerial",
    "required_topics": ["safety"],
    "excluded_topics": ["salaries"],
    "output_format": "markdown",
    "min_judge_score": 16,
    "max_package_length_tokens": 2000,
    "source_reference_level": "page",
}


def _node_body(node_id: str, layer: int, parent: str | None, **fields: object) -> dict[str, object]:
    return {
        "node_id": node_id,
        "name": node_id,
        "layer_index": layer,
        "parent_node_id": parent,
        "activity_area": "offshore production",
        "reporting_rule": "weekly",
        "is_internal_structure_tracked": True,
        **fields,
    }


@pytest.fixture
def client() -> TestClient:
    nodes = InMemoryNodeRepository()
    layers = InMemoryLayerRepository(registry_layers())
    clock = FakeClock(NOW)
    publisher = InMemoryEventPublisher()
    router = create_organization_router(
        register_node_handler=RegisterNodeHandler(
            node_repository=nodes, layer_repository=layers, clock=clock, event_publisher=publisher
        ),
        define_transfer_rule_handler=DefineTransferRuleHandler(
            layer_repository=layers, clock=clock, event_publisher=publisher
        ),
        queries=HierarchyQueries(layer_repository=layers, node_repository=nodes),
    )
    ingestions = InMemoryKnowledgeIngestionRepository(InMemoryKnowledgeItemRepository())
    return build_api_client(
        ingestions=ingestions,
        contents=InMemoryExtractedContentRepository(),
        chunks=InMemoryKnowledgeChunkRepository(ingestions.item_repository),
        queue_monitor=FakeIngestionQueueMonitor([]),
        extra_routers=[router],
    )


def _register(client: TestClient, body: dict[str, object]):  # type: ignore[no-untyped-def]
    return client.post("/organization/nodes", json=body)


def test_layers_are_listed_with_their_detail_levels_when_asked(client: TestClient):
    layers = client.get("/organization/layers").json()["layers"]

    assert [layer["layer_index"] for layer in layers] == [0, 1, 2, 3, 4]
    assert [layer["received_detail_level"] for layer in layers] == [
        "top_executive",
        "managerial",
        "technical_summary",
        "detailed_technical",
        None,
    ]
    assert all(layer["transfer_rule"] is None for layer in layers)


def test_node_is_created_with_201_and_listed_when_registered_under_its_parent(
    client: TestClient,
):
    assert _register(client, _node_body("holding", 0, None)).status_code == 201

    response = _register(client, _node_body("platform_a", 1, "holding"))
    listed = client.get("/organization/nodes").json()["nodes"]

    assert response.status_code == 201
    assert response.json()["parent_node_id"] == "holding"
    assert [node["node_id"] for node in listed] == ["holding", "platform_a"]


def test_problem_details_are_returned_when_a_node_below_layer_0_has_no_parent(
    client: TestClient,
):
    response = _register(client, _node_body("platform_a", 1, None))

    assert response.status_code == 422
    assert response.json()["type"] == "ORGANIZATION_PARENT_NODE_REQUIRED"


def test_problem_details_are_returned_when_the_parent_is_a_terminal_node(client: TestClient):
    _register(client, _node_body("holding", 0, None, is_internal_structure_tracked=False))

    response = _register(client, _node_body("platform_a", 1, "holding"))

    assert response.status_code == 422
    assert response.json()["type"] == "ORGANIZATION_PARENT_STRUCTURE_NOT_TRACKED"


def test_request_is_invalid_when_the_layer_is_not_in_the_hierarchy(client: TestClient):
    response = _register(client, _node_body("platform_a", 7, None))

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


def test_transfer_rule_is_stored_when_defined_for_a_layer(client: TestClient):
    response = client.put("/organization/layers/1/transfer-rule", json=RULE)
    layer = client.get("/organization/layers").json()["layers"][1]

    assert response.status_code == 200
    assert layer["transfer_rule"] == {
        "required_topics": ["safety"],
        "excluded_topics": ["salaries"],
        "output_format": "markdown",
        "min_judge_score": 16,
        "max_package_length_tokens": 2000,
        "source_reference_level": "page",
    }


def test_problem_details_are_returned_when_a_topic_is_both_required_and_excluded(
    client: TestClient,
):
    response = client.put(
        "/organization/layers/1/transfer-rule", json={**RULE, "excluded_topics": ["safety"]}
    )

    assert response.status_code == 422
    assert response.json()["type"] == "ORGANIZATION_TRANSFER_TOPIC_REQUIRED_AND_EXCLUDED"


def test_problem_details_are_returned_when_layer_4_is_given_transfer_rules(client: TestClient):
    response = client.put("/organization/layers/4/transfer-rule", json=RULE)

    assert response.status_code == 422
    assert response.json()["type"] == "ORGANIZATION_LAYER_RECEIVES_NO_PACKAGE"
