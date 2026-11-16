import json
from collections.abc import Iterator
from datetime import UTC, datetime

import psycopg
import pytest
import structlog

from offline_rag.issue.domain.issue import Issue
from offline_rag.issue.domain.issue_priority import IssuePriority
from offline_rag.issue.domain.issue_status import IssueStatus
from offline_rag.issue.infrastructure.postgres_database import PostgresDatabase
from offline_rag.issue.infrastructure.postgres_issue_repository import PostgresIssueRepository
from offline_rag.issue.interface.cli import EXIT_FAILED, EXIT_OK, main
from offline_rag.settings import Settings
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 14, 15, 0, tzinfo=UTC)
ISSUE_ID = "riser-r3"


@pytest.fixture(autouse=True)
def _reset_logging() -> Iterator[None]:
    # `main` configures structlog for the whole process; later tests need the defaults.
    yield
    structlog.reset_defaults()


def _stored_issue(repository: PostgresIssueRepository, *sub_issue_ids: str) -> Issue:
    issue = Issue.raise_issue(
        issue_id=ISSUE_ID,
        owner_node_id=NodeIdentifier("platform_sp12"),
        title="Riser R-3 splash zone corrosion",
        description="Gas export riser R-3 is losing wall in the splash zone.",
        metadata=MetadataRecord(),
        raised_at=NOW,
    )
    for sub_issue_id in sub_issue_ids:
        issue.add_sub_issue(
            sub_issue_id=sub_issue_id,
            parent_id=ISSUE_ID,
            title=f"Title of {sub_issue_id}",
            description=f"Description of {sub_issue_id}",
            metadata=MetadataRecord(),
            added_at=NOW,
        )
    repository.add(issue)
    return repository.get_by_id(ISSUE_ID)


def test_priority_order_and_dependencies_survive_a_round_trip_when_saved(
    database: PostgresDatabase,
):
    repository = PostgresIssueRepository(database)
    issue = _stored_issue(repository, "survey", "wrap", "repair")

    issue.set_priority(IssuePriority.HIGH, set_at=NOW)
    # Every sibling changes place in one save, which the deferred place check allows.
    issue.move_sub_issue("repair", position=1, moved_at=NOW)
    issue.add_sub_issue_dependency("repair", depends_on_sub_issue_id="survey", added_at=NOW)
    issue.add_sub_issue_dependency("repair", depends_on_sub_issue_id="wrap", added_at=NOW)
    repository.save(issue)
    stored = repository.get_by_id(ISSUE_ID)

    assert stored.priority == IssuePriority.HIGH
    assert [sub.sub_issue_id for sub in stored.children_of(ISSUE_ID)] == [
        "repair",
        "survey",
        "wrap",
    ]
    assert stored.children_of(ISSUE_ID)[0].depends_on == ("survey", "wrap")

    stored.remove_sub_issue_dependency("repair", depends_on_sub_issue_id="wrap", removed_at=NOW)
    repository.save(stored)
    assert repository.get_by_id(ISSUE_ID).children_of(ISSUE_ID)[0].depends_on == ("survey",)


def test_resolution_survives_a_round_trip_when_the_issue_is_resolved(database: PostgresDatabase):
    repository = PostgresIssueRepository(database)
    issue = _stored_issue(repository, "survey")
    issue.change_status(IssueStatus.RESOLVED, changed_at=NOW, sub_issue_id="survey")
    issue.resolve("Section replaced in March.", resolved_at=NOW)

    repository.save(issue)
    stored = repository.get_by_id(ISSUE_ID)

    assert (stored.status, stored.resolution_summary) == (
        IssueStatus.RESOLVED,
        "Section replaced in March.",
    )
    assert stored.sub_issues[0].status == IssueStatus.RESOLVED


def test_database_refuses_a_resolved_issue_without_a_summary_when_written_directly(
    database: PostgresDatabase, postgres_url: str
):
    _stored_issue(PostgresIssueRepository(database))

    with (
        psycopg.connect(postgres_url) as connection,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        connection.execute("UPDATE issue SET status = 'resolved' WHERE issue_id = %s", (ISSUE_ID,))


def _run(arguments: list[str], settings: Settings, capsys: pytest.CaptureFixture[str]) -> dict:  # type: ignore[type-arg]
    assert main(arguments, settings=settings) == EXIT_OK
    return json.loads(capsys.readouterr().out)  # type: ignore[no-any-return]


def _problem(arguments: list[str], settings: Settings, capsys: pytest.CaptureFixture[str]) -> str:
    assert main(arguments, settings=settings) == EXIT_FAILED
    return str(json.loads(capsys.readouterr().err.strip().splitlines()[-1])["type"])


def test_cli_runs_an_issue_from_priority_to_resolution(
    settings: Settings, database: PostgresDatabase, capsys: pytest.CaptureFixture[str]
):
    _stored_issue(PostgresIssueRepository(database), "survey", "repair")

    prioritized = _run(["set-priority", ISSUE_ID, "critical"], settings, capsys)
    moved = _run(["move-sub-issue", ISSUE_ID, "repair", "--position", "1"], settings, capsys)
    waiting = _run(["add-dependency", ISSUE_ID, "repair", "--on", "survey"], settings, capsys)
    cycle = _problem(["add-dependency", ISSUE_ID, "survey", "--on", "repair"], settings, capsys)
    started = _run(["change-status", ISSUE_ID, "in_execution"], settings, capsys)
    too_early = _problem(["resolve", ISSUE_ID, "--summary", "Done."], settings, capsys)
    for sub_issue_id in ("survey", "repair"):
        _run(["change-status", ISSUE_ID, "resolved", "--sub-issue", sub_issue_id], settings, capsys)
    resolved = _run(["resolve", ISSUE_ID, "--summary", "Section replaced."], settings, capsys)
    closed = _problem(["set-priority", ISSUE_ID, "low"], settings, capsys)

    assert prioritized["priority"] == "critical"
    assert [sub["sub_issue_id"] for sub in moved["sub_issues"]] == ["repair", "survey"]
    assert waiting["sub_issues"][0]["depends_on"] == ["survey"]
    assert cycle == "ISSUE_SUB_ISSUE_DEPENDENCY_CYCLE"
    assert started["status"] == "in_execution"
    assert too_early == "ISSUE_HAS_OPEN_SUB_ISSUES"
    assert (resolved["status"], resolved["resolution_summary"]) == ("resolved", "Section replaced.")
    assert closed == "ISSUE_CLOSED"


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        (["change-status", ISSUE_ID, "resolved"], "ISSUE_RESOLVE_REQUIRED"),
        (
            ["move-sub-issue", ISSUE_ID, "survey", "--position", "5"],
            "ISSUE_SUB_ISSUE_POSITION_OUT_OF_RANGE",
        ),
        (
            ["remove-dependency", ISSUE_ID, "survey", "--on", "survey"],
            "ISSUE_SUB_ISSUE_DEPENDENCY_NOT_FOUND",
        ),
        (
            ["change-status", ISSUE_ID, "analyzing", "--sub-issue", "missing"],
            "ISSUE_SUB_ISSUE_NOT_FOUND",
        ),
    ],
)
def test_cli_prints_problem_details_when_a_lifecycle_rule_is_broken(
    settings: Settings,
    database: PostgresDatabase,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    code: str,
):
    _stored_issue(PostgresIssueRepository(database), "survey")

    assert _problem(arguments, settings, capsys) == code
