import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import structlog

from offline_rag.bootstrap import build_knowledge
from offline_rag.issue.application.errors import KnowledgeItemNotFoundError
from offline_rag.issue.domain.issue import Issue
from offline_rag.issue.domain.sub_issue_candidate import Citation, SubIssueCandidate
from offline_rag.issue.infrastructure.knowledge_management_reader import (
    KnowledgeManagementReader,
)
from offline_rag.issue.infrastructure.postgres_database import PostgresDatabase
from offline_rag.issue.infrastructure.postgres_issue_repository import PostgresIssueRepository
from offline_rag.issue.interface.cli import EXIT_FAILED, EXIT_OK, main
from offline_rag.knowledge.application.commands import RunIngestionStep, SubmitKnowledgeItem
from offline_rag.knowledge.application.ports import IngestionLane
from offline_rag.knowledge.domain.knowledge_scope import ConfidentialityLevel, KnowledgeScope
from offline_rag.settings import Settings
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parents[3]
INSPECTION_V2 = ROOT / "fixtures" / "docs" / "cases" / "inspection_sp12_riser_r3_2026_v2.docx"
PLATFORM = NodeIdentifier("platform_sp12")
CITATION = Citation(doc_id="ins-02-v2", page_or_section="4.", quote="Install a wrap.")


@pytest.fixture(autouse=True)
def _reset_logging() -> Iterator[None]:
    # `main` configures structlog for the whole process; later tests need the defaults.
    yield
    structlog.reset_defaults()


@pytest.fixture
def chunked_item_id(settings: Settings) -> str:
    """Submit the 2026 R-3 inspection report and run its text and chunking steps."""
    knowledge = build_knowledge(settings)
    try:
        receipt = knowledge.submit_handler.submit(
            SubmitKnowledgeItem(
                owner_node_id=NodeIdentifier("sp12_inspection_team"),
                source_file_name=INSPECTION_V2.name,
                content=INSPECTION_V2.read_bytes(),
                scope=KnowledgeScope(confidentiality=ConfidentialityLevel.INTERNAL),
            )
        )
        for lane in (IngestionLane.TEXT, IngestionLane.CHUNKING):
            knowledge.run_step_handler.run(
                RunIngestionStep(ingestion_id=receipt.ingestion_id, lane=lane)
            )
    finally:
        knowledge.close()
    return receipt.item_id


def _riser_issue(issue_id: str = "riser-r3") -> Issue:
    issue = Issue.raise_issue(
        issue_id=issue_id,
        owner_node_id=PLATFORM,
        title="Riser R-3 splash zone corrosion",
        description="Gas export riser R-3 is losing wall in the splash zone.",
        metadata=MetadataRecord(),
        raised_at=datetime(2026, 11, 14, 9, 0, tzinfo=UTC),
    )
    issue.pull_events()
    return issue


def _candidates() -> list[SubIssueCandidate]:
    return [
        SubIssueCandidate(
            number=1, title="Temporary wrap", description="Wrap it.", citations=(CITATION,)
        ),
        SubIssueCandidate(number=2, title="UT survey", description="Survey it."),
    ]


def test_reader_returns_the_active_chunks_with_their_headings_when_an_item_is_chunked(
    settings: Settings, chunked_item_id: str
):
    knowledge = build_knowledge(settings)
    try:
        passages = KnowledgeManagementReader(knowledge.queries).passages_of([chunked_item_id])
    finally:
        knowledge.close()

    assert passages
    assert {passage.item_id for passage in passages} == {chunked_item_id}
    assert all(passage.text and passage.token_count > 0 for passage in passages)
    assert any(passage.page_or_section for passage in passages)
    assert any("splash zone wrap" in passage.text for passage in passages)


def test_reader_raises_an_issue_error_when_the_item_does_not_exist(settings: Settings):
    knowledge = build_knowledge(settings)
    try:
        with pytest.raises(KnowledgeItemNotFoundError):
            KnowledgeManagementReader(knowledge.queries).passages_of(["missing"])
    finally:
        knowledge.close()


def test_candidates_survive_a_round_trip_when_accepted_and_saved(database: PostgresDatabase):
    repository = PostgresIssueRepository(database)
    issue = _riser_issue()
    issue.propose_sub_issue_candidates(_candidates())
    repository.add(issue)

    loaded = repository.get_by_id("riser-r3")
    loaded.accept_sub_issue_candidates(
        numbers=[2], sub_issue_ids=["sub-survey"], accepted_at=datetime.now(UTC)
    )
    repository.save(loaded)
    stored = repository.get_by_id("riser-r3")

    assert stored.sub_issue_candidates == (
        _candidates()[0],
        SubIssueCandidate(
            number=2,
            title="UT survey",
            description="Survey it.",
            accepted_sub_issue_id="sub-survey",
        ),
    )
    assert [sub.sub_issue_id for sub in stored.sub_issues] == ["sub-survey"]


def test_new_suggestions_replace_the_waiting_ones_when_saved(database: PostgresDatabase):
    repository = PostgresIssueRepository(database)
    issue = _riser_issue()
    issue.propose_sub_issue_candidates(_candidates())
    repository.add(issue)

    loaded = repository.get_by_id("riser-r3")
    loaded.propose_sub_issue_candidates(
        [SubIssueCandidate(number=1, title="Repair option", description="Choose one.")]
    )
    repository.save(loaded)

    stored = repository.get_by_id("riser-r3").sub_issue_candidates
    assert [(candidate.number, candidate.title) for candidate in stored] == [(3, "Repair option")]


def _run(arguments: list[str], settings: Settings, capsys: pytest.CaptureFixture[str]) -> dict:  # type: ignore[type-arg]
    assert main(arguments, settings=settings) == EXIT_OK
    return json.loads(capsys.readouterr().out)  # type: ignore[no-any-return]


def test_cli_accepts_chosen_candidates_as_sub_issues(
    settings: Settings, database: PostgresDatabase, capsys: pytest.CaptureFixture[str]
):
    issue = _riser_issue()
    issue.propose_sub_issue_candidates(_candidates())
    PostgresIssueRepository(database).add(issue)

    accepted = _run(["accept-sub-issue-candidates", "riser-r3", "2", "1"], settings, capsys)
    shown = _run(["show", "riser-r3"], settings, capsys)

    assert [sub["title"] for sub in accepted["sub_issues"]] == ["UT survey", "Temporary wrap"]
    assert [candidate["accepted_sub_issue_id"] for candidate in shown["sub_issue_candidates"]] == [
        accepted["sub_issues"][1]["sub_issue_id"],
        accepted["sub_issues"][0]["sub_issue_id"],
    ]
    assert shown["sub_issue_candidates"][0]["citations"] == [
        {"doc_id": "ins-02-v2", "page_or_section": "4.", "quote": "Install a wrap."}
    ]


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        (["accept-sub-issue-candidates", "riser-r3", "9"], "ISSUE_SUB_ISSUE_CANDIDATE_NOT_FOUND"),
        (
            ["decompose", "riser-r3", "--knowledge-item", "missing"],
            "ISSUE_KNOWLEDGE_ITEM_NOT_FOUND",
        ),
    ],
)
def test_cli_prints_problem_details_when_a_candidate_or_item_is_missing(
    settings: Settings,
    database: PostgresDatabase,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    code: str,
):
    PostgresIssueRepository(database).add(_riser_issue())

    assert main(arguments, settings=settings) == EXIT_FAILED

    problem = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert problem["type"] == code


def test_cli_stores_nothing_when_the_model_does_not_answer(
    settings: Settings,
    database: PostgresDatabase,
    chunked_item_id: str,
    capsys: pytest.CaptureFixture[str],
):
    PostgresIssueRepository(database).add(_riser_issue())

    exit_code = main(
        ["decompose", "riser-r3", "--knowledge-item", chunked_item_id], settings=settings
    )

    problem = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert exit_code == EXIT_FAILED
    assert problem["type"] == "ISSUE_MODEL_UNAVAILABLE"
    assert PostgresIssueRepository(database).get_by_id("riser-r3").sub_issue_candidates == ()
