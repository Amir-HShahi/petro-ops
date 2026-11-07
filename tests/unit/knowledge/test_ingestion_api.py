from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from tests.fakes.knowledge import (
    FakeClock,
    FakeIdGenerator,
    FakeIngestionQueueMonitor,
    FakeNodeDirectory,
    InMemoryEventPublisher,
    InMemoryExtractedContentRepository,
    InMemoryKnowledgeIngestionRepository,
    InMemoryKnowledgeItemRepository,
    InMemoryOutbox,
    InMemorySourceFileStore,
)

from offline_rag.knowledge.application.knowledge_ingestion_queries import (
    KnowledgeIngestionQueries,
)
from offline_rag.knowledge.application.ports import IngestionQueueDepth
from offline_rag.knowledge.application.reingest_knowledge_item import (
    ReingestKnowledgeItemHandler,
)
from offline_rag.knowledge.application.submit_knowledge_item import (
    BYTES_PER_MB,
    SubmitKnowledgeItemHandler,
)
from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.extracted_content import ContentBlock, ExtractedContent
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.knowledge.infrastructure.errors import QueueMonitorUnavailableError
from offline_rag.knowledge.interface.api import PROBLEM_MEDIA_TYPE, REQUEST_ID_HEADER, create_app

NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
NODE_ID = "sp12_inspection_team"
PDF_CONTENT = b"%PDF-1.7\nriser R-3 wall thickness"
MAX_FILE_MB = 1
CONTENT = ExtractedContent(
    document_format=DocumentFormat.PDF,
    page_count=2,
    blocks=(
        ContentBlock.paragraph(order=0, text="Riser R-3 wall loss.", page_number=1),
        ContentBlock.table(order=1, rows=[["Location", "Measured (mm)"]], page_number=1),
    ),
)


@pytest.fixture
def ingestions() -> InMemoryKnowledgeIngestionRepository:
    return InMemoryKnowledgeIngestionRepository(InMemoryKnowledgeItemRepository())


@pytest.fixture
def contents() -> InMemoryExtractedContentRepository:
    return InMemoryExtractedContentRepository()


@pytest.fixture
def queue_monitor() -> FakeIngestionQueueMonitor:
    return FakeIngestionQueueMonitor(
        [IngestionQueueDepth(queue="ingestion", messages_ready=2, messages_unacked=1, consumers=3)]
    )


@pytest.fixture
def client(
    ingestions: InMemoryKnowledgeIngestionRepository,
    contents: InMemoryExtractedContentRepository,
    queue_monitor: FakeIngestionQueueMonitor,
) -> TestClient:
    clock = FakeClock(NOW)
    id_generator = FakeIdGenerator()
    app = create_app(
        submit_handler=SubmitKnowledgeItemHandler(
            ingestion_repository=ingestions,
            node_directory=FakeNodeDirectory([NODE_ID]),
            source_file_store=InMemorySourceFileStore(),
            clock=clock,
            id_generator=id_generator,
            event_publisher=InMemoryEventPublisher(),
            max_file_mb=MAX_FILE_MB,
        ),
        reingest_handler=ReingestKnowledgeItemHandler(
            ingestion_repository=ingestions,
            repository=ingestions.item_repository,
            clock=clock,
            id_generator=id_generator,
        ),
        queries=KnowledgeIngestionQueries(
            ingestion_repository=ingestions,
            repository=ingestions.item_repository,
            extracted_content_repository=contents,
            outbox=InMemoryOutbox(ingestions),
            node_directory=FakeNodeDirectory([NODE_ID, "platform_sp12"]),
            queue_monitor=queue_monitor,
        ),
        max_file_mb=MAX_FILE_MB,
        min_page_text_chars=20,
    )
    return TestClient(app, raise_server_exceptions=False)


def _submit(client: TestClient, content: bytes = PDF_CONTENT, **fields: object):  # type: ignore[no-untyped-def]
    return client.post(
        "/knowledge-items",
        files={"file": ("report.pdf", content, "application/pdf")},
        data={"node_id": NODE_ID, **fields},
    )


def _complete(ingestions: InMemoryKnowledgeIngestionRepository, ingestion_id: str) -> None:
    ingestion = ingestions.get_by_id(ingestion_id)
    ingestion.start_extraction(NOW)
    ingestion.complete(blocks_for_review=0, now=NOW)
    ingestions.save(ingestion)


def test_health_is_ok_when_the_api_is_up(client: TestClient):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ingestion_is_queued_with_202_when_file_is_submitted(client: TestClient):
    response = _submit(client, document_type="project_report", tags=["riser", "ut"])

    body = response.json()
    assert response.status_code == 202
    assert body["status"] == "queued"
    assert body["version_tag"] == "v1"
    assert response.headers["Location"] == f"/knowledge-ingestions/{body['ingestion_id']}"


def test_metadata_is_recorded_when_file_is_submitted_with_form_fields(
    client: TestClient, ingestions: InMemoryKnowledgeIngestionRepository
):
    item_id = _submit(client, document_type="project_report", tags=["riser", "ut"]).json()[
        "item_id"
    ]

    metadata = ingestions.item_repository.get_by_id(item_id).active_version.metadata
    assert metadata.document_type == "project_report"
    assert metadata.tags == ("riser", "ut")


def test_problem_details_are_returned_when_the_node_is_unknown(client: TestClient):
    response = _submit(client, node_id="no_such_node")

    problem = response.json()
    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert problem["type"] == "KNOWLEDGE_OWNER_NODE_NOT_FOUND"
    assert problem["request_id"] == response.headers[REQUEST_ID_HEADER]


def test_file_is_refused_when_it_is_larger_than_the_limit(client: TestClient):
    response = _submit(client, content=PDF_CONTENT.ljust(MAX_FILE_MB * BYTES_PER_MB + 1, b" "))

    assert response.status_code == 422
    assert response.json()["type"] == "KNOWLEDGE_FILE_TOO_LARGE"


def test_request_is_invalid_when_a_required_field_is_missing(client: TestClient):
    response = client.post(
        "/knowledge-items", files={"file": ("report.pdf", PDF_CONTENT, "application/pdf")}
    )

    problem = response.json()
    assert response.status_code == 422
    assert problem["type"] == "KNOWLEDGE_REQUEST_INVALID"
    assert [entry["field"] for entry in problem["details"]["problems"]] == ["body.node_id"]


def test_request_is_invalid_when_confidentiality_is_not_a_known_level(client: TestClient):
    response = _submit(client, confidentiality="top_secret")

    assert response.status_code == 422
    assert response.json()["type"] == "KNOWLEDGE_REQUEST_INVALID"


def test_status_is_returned_when_ingestion_exists(client: TestClient):
    ingestion_id = _submit(client).json()["ingestion_id"]

    response = client.get(f"/knowledge-ingestions/{ingestion_id}")

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert response.json()["attempts"] == 0


def test_not_found_is_returned_when_ingestion_does_not_exist(client: TestClient):
    response = client.get("/knowledge-ingestions/no-such-ingestion")

    assert response.status_code == 404
    assert response.json()["type"] == "KNOWLEDGE_INGESTION_NOT_FOUND"


def test_blocks_are_returned_when_content_was_extracted(
    client: TestClient, contents: InMemoryExtractedContentRepository
):
    item_id = _submit(client).json()["item_id"]
    contents.save(item_id, VersionTag("v1"), CONTENT)

    response = client.get(f"/knowledge-items/{item_id}/versions/v1/content", params={"limit": 1})

    body = response.json()
    assert response.status_code == 200
    assert body["extraction"]["block_count"] == 2
    assert body["extraction"]["pages_without_text"] == [2]
    assert [block["page_number"] for block in body["blocks"]] == [1]


def test_not_found_is_returned_when_nothing_was_extracted_yet(client: TestClient):
    item_id = _submit(client).json()["item_id"]

    response = client.get(f"/knowledge-items/{item_id}/versions/v1/content")

    assert response.status_code == 404
    assert response.json()["type"] == "KNOWLEDGE_EXTRACTED_CONTENT_NOT_FOUND"


def test_new_ingestion_is_queued_when_the_last_one_ended(
    client: TestClient, ingestions: InMemoryKnowledgeIngestionRepository
):
    submitted = _submit(client).json()
    _complete(ingestions, submitted["ingestion_id"])

    response = client.post(f"/knowledge-items/{submitted['item_id']}/versions/v1/ingestions")

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.json()["ingestion_id"] != submitted["ingestion_id"]


def test_reingest_is_refused_when_the_last_ingestion_is_still_running(client: TestClient):
    item_id = _submit(client).json()["item_id"]

    response = client.post(f"/knowledge-items/{item_id}/versions/v1/ingestions")

    assert response.status_code == 422
    assert response.json()["type"] == "KNOWLEDGE_INGESTION_ALREADY_RUNNING"


def test_not_found_is_returned_when_the_version_does_not_exist(client: TestClient):
    item_id = _submit(client).json()["item_id"]

    response = client.post(f"/knowledge-items/{item_id}/versions/v9/ingestions")

    assert response.status_code == 404
    assert response.json()["type"] == "KNOWLEDGE_VERSION_NOT_FOUND"


def test_request_id_from_the_caller_is_reused_when_it_is_plain(client: TestClient):
    response = client.get("/knowledge-ingestions/missing", headers={REQUEST_ID_HEADER: "ui-42"})

    assert response.headers[REQUEST_ID_HEADER] == "ui-42"
    assert response.json()["request_id"] == "ui-42"


def test_new_request_id_is_made_when_the_callers_one_is_not_plain(client: TestClient):
    response = client.get("/health", headers={REQUEST_ID_HEADER: "bad id with spaces"})

    assert response.headers[REQUEST_ID_HEADER] != "bad id with spaces"
    assert len(response.headers[REQUEST_ID_HEADER]) == 8


def test_recent_ingestions_carry_their_file_when_listed(client: TestClient):
    ingestion_id = _submit(client).json()["ingestion_id"]

    response = client.get("/knowledge-ingestions", params={"limit": 5})

    [listed] = response.json()["ingestions"]
    assert response.status_code == 200
    assert listed["ingestion_id"] == ingestion_id
    assert listed["status"] == "queued"
    assert listed["source_file_name"] == "report.pdf"
    assert listed["document_format"] == "pdf"


def test_recent_ingestions_are_limited_when_a_limit_is_given(client: TestClient):
    _submit(client)
    _submit(client, content=PDF_CONTENT + b" second")

    response = client.get("/knowledge-ingestions", params={"limit": 1})

    assert len(response.json()["ingestions"]) == 1


@pytest.mark.parametrize("limit", [0, 101])
def test_recent_ingestions_are_refused_when_the_limit_is_out_of_range(
    client: TestClient, limit: int
):
    response = client.get("/knowledge-ingestions", params={"limit": limit})

    assert response.status_code == 422
    assert response.json()["type"] == "KNOWLEDGE_REQUEST_INVALID"


def test_queues_and_unpublished_messages_are_returned_when_asked(client: TestClient):
    _submit(client)

    response = client.get("/ingestion-queues")

    assert response.status_code == 200
    assert response.json() == {
        "queues": [
            {"queue": "ingestion", "messages_ready": 2, "messages_unacked": 1, "consumers": 3}
        ],
        "unpublished_outbox_messages": 1,
    }


def test_queues_answer_503_when_the_management_api_is_unavailable(
    client: TestClient, queue_monitor: FakeIngestionQueueMonitor
):
    queue_monitor.error = QueueMonitorUnavailableError()

    response = client.get("/ingestion-queues")

    assert response.status_code == 503
    assert response.json()["type"] == "KNOWLEDGE_QUEUE_MONITOR_UNAVAILABLE"


def test_registered_nodes_are_listed_sorted_when_asked(client: TestClient):
    response = client.get("/nodes")

    assert response.json() == {"nodes": [{"node_id": "platform_sp12"}, {"node_id": NODE_ID}]}


def test_pipeline_page_is_served_with_its_assets_when_opened(client: TestClient):
    page = client.get("/pipeline")
    css = client.get("/pipeline/assets/pipeline.css")
    script = client.get("/pipeline/assets/pipeline.js")

    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert "/pipeline/assets/pipeline.js" in page.text
    assert css.status_code == 200
    assert script.status_code == 200


def test_pipeline_page_loads_nothing_from_other_hosts_when_opened(client: TestClient):
    sources = [
        client.get(path).text
        for path in ("/pipeline", "/pipeline/assets/pipeline.css", "/pipeline/assets/pipeline.js")
    ]

    assert not any("http://" in source or "https://" in source for source in sources)
