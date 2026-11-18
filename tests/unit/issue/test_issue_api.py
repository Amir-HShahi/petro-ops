import pytest
from fastapi.testclient import TestClient
from tests.fakes.issue import FakeIssueDecomposer, FakeKnowledgeReader, InMemoryIssueRepository
from tests.fakes.knowledge import (
    FakeClock,
    FakeIdGenerator,
    FakeIngestionQueueMonitor,
    FakeNodeDirectory,
    InMemoryEventPublisher,
    InMemoryExtractedContentRepository,
    InMemoryKnowledgeChunkRepository,
    InMemoryKnowledgeIngestionRepository,
    InMemoryKnowledgeItemRepository,
)
from tests.fakes.knowledge_api import NOW, build_api_client

from offline_rag.issue.application.accept_sub_issue_candidates import (
    AcceptSubIssueCandidatesHandler,
)
from offline_rag.issue.application.add_sub_issue import AddSubIssueHandler
from offline_rag.issue.application.add_sub_issue_dependency import AddSubIssueDependencyHandler
from offline_rag.issue.application.change_issue_status import ChangeIssueStatusHandler
from offline_rag.issue.application.decompose_issue import DecomposeIssueHandler
from offline_rag.issue.application.issue_queries import IssueQueries
from offline_rag.issue.application.move_sub_issue import MoveSubIssueHandler
from offline_rag.issue.application.ports import Decomposition, KnowledgePassage
from offline_rag.issue.application.raise_issue import RaiseIssueHandler
from offline_rag.issue.application.remove_sub_issue_dependency import (
    RemoveSubIssueDependencyHandler,
)
from offline_rag.issue.application.resolve_issue import ResolveIssueHandler
from offline_rag.issue.application.set_issue_priority import SetIssuePriorityHandler
from offline_rag.issue.domain.similar_issue import SimilarIssueDetector
from offline_rag.issue.domain.sub_issue_candidate import Citation, SubIssueCandidate
from offline_rag.issue.interface.api import IssueRouteHandlers, create_issue_router

PASSAGE = KnowledgePassage(
    item_id="ins-02-v2",
    page_or_section="4. Recommendation",
    text="Install a temporary splash zone wrap within 6 months.",
    token_count=12,
)
DECOMPOSITION = Decomposition(
    candidates=(
        SubIssueCandidate(
            number=1,
            title="Temporary splash zone wrap",
            description="Wrap the splash zone until a repair is in place.",
            citations=(
                Citation(
                    doc_id="ins-02-v2",
                    page_or_section="4. Recommendation",
                    quote="Install a temporary splash zone wrap within 6 months.",
                ),
            ),
        ),
        SubIssueCandidate(number=2, title="UT survey", description="Survey the wall."),
    ),
    missing_information="No repair cost estimate.",
)
RISER = {
    "owner_node_id": "platform_sp12",
    "title": "Riser R-3 splash zone corrosion",
    "description": "Gas export riser R-3 is losing wall in the splash zone.",
    "domain": "asset integrity",
    "tags": ["riser"],
}


@pytest.fixture
def client() -> TestClient:
    issues = InMemoryIssueRepository()
    clock = FakeClock(NOW)
    ids = FakeIdGenerator("id")
    publisher = InMemoryEventPublisher()
    common = {"issue_repository": issues, "clock": clock, "event_publisher": publisher}
    router = create_issue_router(
        IssueRouteHandlers(
            raise_issue=RaiseIssueHandler(
                node_directory=FakeNodeDirectory(["platform_sp12"]),
                id_generator=ids,
                detector=SimilarIssueDetector(duplicate_from=0.40, overlap_from=0.25),
                **common,
            ),
            add_sub_issue=AddSubIssueHandler(id_generator=ids, **common),
            decompose_issue=DecomposeIssueHandler(
                issue_repository=issues,
                knowledge_reader=FakeKnowledgeReader([PASSAGE]),
                decomposer=FakeIssueDecomposer(DECOMPOSITION),
            ),
            accept_sub_issue_candidates=AcceptSubIssueCandidatesHandler(id_generator=ids, **common),
            set_priority=SetIssuePriorityHandler(**common),
            move_sub_issue=MoveSubIssueHandler(**common),
            add_dependency=AddSubIssueDependencyHandler(**common),
            remove_dependency=RemoveSubIssueDependencyHandler(**common),
            change_status=ChangeIssueStatusHandler(**common),
            resolve_issue=ResolveIssueHandler(**common),
            queries=IssueQueries(issue_repository=issues),
        )
    )
    ingestions = InMemoryKnowledgeIngestionRepository(InMemoryKnowledgeItemRepository())
    return build_api_client(
        ingestions=ingestions,
        contents=InMemoryExtractedContentRepository(),
        chunks=InMemoryKnowledgeChunkRepository(ingestions.item_repository),
        queue_monitor=FakeIngestionQueueMonitor([]),
        extra_routers=[router],
    )


def _raise(client: TestClient) -> dict:  # type: ignore[type-arg]
    response = client.post("/issues", json=RISER)
    assert response.status_code == 201
    return response.json()  # type: ignore[no-any-return]


def _add(client: TestClient, issue_id: str, title: str, parent_id: str | None = None) -> str:
    response = client.post(
        f"/issues/{issue_id}/sub-issues",
        json={"parent_id": parent_id, "title": title, "description": f"About {title}."},
    )
    assert response.status_code == 201
    return str(response.json()["added_sub_issue_id"])


def test_raised_issue_is_listed_and_shown_with_its_metadata(client: TestClient):
    raised = _raise(client)

    listed = client.get("/issues", params={"node": "platform_sp12"}).json()
    shown = client.get(f"/issues/{raised['issue_id']}").json()

    assert [issue["issue_id"] for issue in listed["issues"]] == [raised["issue_id"]]
    assert shown == raised
    assert raised["metadata"]["domain"] == "asset integrity"
    assert raised["metadata"]["tags"] == ["riser"]


def test_second_raise_of_the_same_problem_is_flagged(client: TestClient):
    first = _raise(client)

    again = client.post("/issues", json=RISER).json()

    assert [(flag["issue_id"], flag["kind"]) for flag in again["similar_issues"]] == [
        (first["issue_id"], "duplicate")
    ]


def test_sub_issues_are_added_nested_and_reordered(client: TestClient):
    issue_id = _raise(client)["issue_id"]
    survey = _add(client, issue_id, "UT survey")
    repair = _add(client, issue_id, "Repair option")
    _add(client, issue_id, "Clamp-on sleeve", parent_id=repair)

    moved = client.put(
        f"/issues/{issue_id}/sub-issues/{repair}/position", json={"position": 1}
    ).json()

    assert [sub["sub_issue_id"] for sub in moved["sub_issues"]] == [repair, survey]
    assert [sub["title"] for sub in moved["sub_issues"][0]["sub_issues"]] == ["Clamp-on sleeve"]


def test_dependency_is_added_refused_in_a_circle_and_removed(client: TestClient):
    issue_id = _raise(client)["issue_id"]
    survey = _add(client, issue_id, "UT survey")
    repair = _add(client, issue_id, "Repair option")
    path = f"/issues/{issue_id}/sub-issues"

    waiting = client.post(f"{path}/{repair}/dependencies", json={"depends_on_sub_issue_id": survey})
    circle = client.post(f"{path}/{survey}/dependencies", json={"depends_on_sub_issue_id": repair})
    removed = client.delete(f"{path}/{repair}/dependencies/{survey}")

    assert waiting.json()["sub_issues"][1]["depends_on"] == [survey]
    assert circle.status_code == 422
    assert circle.json()["type"] == "ISSUE_SUB_ISSUE_DEPENDENCY_CYCLE"
    assert removed.json()["sub_issues"][1]["depends_on"] == []


def test_decomposition_returns_candidates_that_can_be_accepted(client: TestClient):
    issue_id = _raise(client)["issue_id"]

    decomposed = client.post(
        f"/issues/{issue_id}/decompositions", json={"knowledge_item_ids": ["ins-02-v2"]}
    ).json()
    accepted = client.post(f"/issues/{issue_id}/candidates/accepted", json={"numbers": [2]}).json()

    assert [candidate["title"] for candidate in decomposed["candidates"]] == [
        "Temporary splash zone wrap",
        "UT survey",
    ]
    assert decomposed["candidates"][0]["citations"][0]["doc_id"] == "ins-02-v2"
    assert decomposed["missing_information"] == "No repair cost estimate."
    assert [sub["title"] for sub in accepted["sub_issues"]] == ["UT survey"]
    assert [c["accepted_sub_issue_id"] is not None for c in accepted["sub_issue_candidates"]] == [
        False,
        True,
    ]


def test_decomposition_is_refused_when_no_knowledge_is_named(client: TestClient):
    issue_id = _raise(client)["issue_id"]

    response = client.post(f"/issues/{issue_id}/decompositions", json={"knowledge_item_ids": []})

    assert response.status_code == 422
    assert response.json()["type"] == "ISSUE_KNOWLEDGE_REQUIRED"


def test_issue_runs_from_priority_to_resolution(client: TestClient):
    issue_id = _raise(client)["issue_id"]
    survey = _add(client, issue_id, "UT survey")

    prioritized = client.put(f"/issues/{issue_id}/priority", json={"priority": "high"}).json()
    early = client.post(f"/issues/{issue_id}/resolution", json={"resolution_summary": "Done."})
    client.put(f"/issues/{issue_id}/status", json={"status": "resolved", "sub_issue_id": survey})
    resolved = client.post(
        f"/issues/{issue_id}/resolution", json={"resolution_summary": "Section replaced."}
    ).json()
    closed = client.put(f"/issues/{issue_id}/priority", json={"priority": "low"})

    assert prioritized["priority"] == "high"
    assert early.json()["type"] == "ISSUE_HAS_OPEN_SUB_ISSUES"
    assert (resolved["status"], resolved["resolution_summary"]) == ("resolved", "Section replaced.")
    assert closed.json()["type"] == "ISSUE_CLOSED"


@pytest.mark.parametrize(
    ("method", "path", "body", "status", "code"),
    [
        ("get", "/issues/missing", None, 404, "ISSUE_NOT_FOUND"),
        ("put", "/issues/{id}/status", {"status": "resolved"}, 422, "ISSUE_RESOLVE_REQUIRED"),
        (
            "post",
            "/issues/{id}/candidates/accepted",
            {"numbers": [7]},
            404,
            "ISSUE_SUB_ISSUE_CANDIDATE_NOT_FOUND",
        ),
    ],
)
def test_refusals_come_back_as_problem_details(
    client: TestClient, method: str, path: str, body: object, status: int, code: str
):
    issue_id = _raise(client)["issue_id"]

    response = client.request(method, path.format(id=issue_id), json=body)

    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"] == code


def test_issue_for_an_unknown_node_is_refused(client: TestClient):
    response = client.post("/issues", json=RISER | {"owner_node_id": "platform_sp99"})

    assert response.status_code == 404
    assert response.json()["type"] == "ISSUE_OWNER_NODE_NOT_FOUND"
