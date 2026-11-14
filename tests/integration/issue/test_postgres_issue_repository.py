import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
import structlog

from offline_rag.bootstrap import build_organization
from offline_rag.issue.application.errors import IssueNotFoundError
from offline_rag.issue.domain.issue import Issue
from offline_rag.issue.domain.similar_issue import SimilarIssueFlag, SimilarIssueKind
from offline_rag.issue.infrastructure.errors import IssueStorageError
from offline_rag.issue.infrastructure.postgres_database import PostgresDatabase
from offline_rag.issue.infrastructure.postgres_issue_repository import PostgresIssueRepository
from offline_rag.issue.interface.cli import EXIT_FAILED, EXIT_OK, main
from offline_rag.organization.interface.node_registry_file import read_node_registry
from offline_rag.settings import Settings
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parents[3]
RAISED_AT = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)
PLATFORM = NodeIdentifier("platform_sp12")


def _issue(issue_id: str, *, owner: NodeIdentifier = PLATFORM, hours: int = 0) -> Issue:
    return Issue.raise_issue(
        issue_id=issue_id,
        owner_node_id=owner,
        title=f"Title of {issue_id}",
        description=f"Description of {issue_id}",
        metadata=MetadataRecord(domain="asset integrity", tags=("riser", "splash zone")),
        raised_at=RAISED_AT + timedelta(hours=hours),
    )


def test_issue_and_its_sub_issue_tree_survive_a_round_trip_when_stored(
    database: PostgresDatabase,
):
    issue = _issue("riser-r3")
    for sub_issue_id, parent_id in [
        ("survey", "riser-r3"),
        ("repair", "riser-r3"),
        ("sleeve", "repair"),
        ("replacement", "repair"),
    ]:
        issue.add_sub_issue(
            sub_issue_id=sub_issue_id,
            parent_id=parent_id,
            title=f"Title of {sub_issue_id}",
            description=f"Description of {sub_issue_id}",
            metadata=MetadataRecord(tags=(sub_issue_id,)),
        )
    repository = PostgresIssueRepository(database)

    repository.add(issue)
    stored = repository.get_by_id("riser-r3")

    assert stored.raised_at == RAISED_AT
    assert stored.metadata == MetadataRecord(
        domain="asset integrity", tags=("riser", "splash zone")
    )
    assert [sub.sub_issue_id for sub in stored.children_of("riser-r3")] == ["survey", "repair"]
    assert [sub.sub_issue_id for sub in stored.children_of("repair")] == ["sleeve", "replacement"]
    assert stored.children_of("repair")[1].metadata == MetadataRecord(tags=("replacement",))


def test_similar_issue_flags_survive_a_round_trip_in_their_order_when_stored(
    database: PostgresDatabase,
):
    repository = PostgresIssueRepository(database)
    flags = (
        SimilarIssueFlag(similar_issue_id="b-older", kind=SimilarIssueKind.DUPLICATE, score=0.41),
        SimilarIssueFlag(similar_issue_id="a-older", kind=SimilarIssueKind.OVERLAP, score=0.37),
        SimilarIssueFlag(similar_issue_id="c-older", kind=SimilarIssueKind.OVERLAP, score=0.26),
    )
    issue = Issue.raise_issue(
        issue_id="riser-r3",
        owner_node_id=PLATFORM,
        title="Riser R-3 wall loss",
        description="Wall loss on riser R-3.",
        metadata=MetadataRecord(),
        raised_at=RAISED_AT,
        similar_issue_flags=flags,
    )

    repository.add(issue)

    assert repository.get_by_id("riser-r3").similar_issue_flags == flags
    assert repository.find_by_owner(PLATFORM)[0].similar_issue_flags == flags


def test_issue_is_not_found_when_its_id_is_unknown(database: PostgresDatabase):
    with pytest.raises(IssueNotFoundError):
        PostgresIssueRepository(database).get_by_id("missing")


def test_only_the_node_issues_are_listed_oldest_first_when_found_by_owner(
    database: PostgresDatabase,
):
    repository = PostgresIssueRepository(database)
    repository.add(_issue("later", hours=2))
    repository.add(_issue("earlier", hours=1))
    repository.add(_issue("other-node", owner=NodeIdentifier("sp12_inspection_team")))

    found = repository.find_by_owner(PLATFORM)

    assert [issue.issue_id for issue in found] == ["earlier", "later"]
    assert repository.find_by_owner(NodeIdentifier("platform_sp14")) == []


def test_storage_error_is_raised_when_an_issue_id_is_taken(database: PostgresDatabase):
    repository = PostgresIssueRepository(database)
    repository.add(_issue("riser-r3"))

    with pytest.raises(IssueStorageError):
        repository.add(_issue("riser-r3"))


def test_database_refuses_an_unknown_status_when_written_directly(
    database: PostgresDatabase, postgres_url: str
):
    PostgresIssueRepository(database).add(_issue("riser-r3"))

    with (
        psycopg.connect(postgres_url) as connection,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        connection.execute("UPDATE issue SET status = 'closed' WHERE issue_id = 'riser-r3'")


@pytest.fixture(autouse=True)
def _reset_logging() -> Iterator[None]:
    # `main` configures structlog for the whole process; later tests need the defaults.
    yield
    structlog.reset_defaults()


@pytest.fixture
def settings(postgres_url: str) -> Settings:
    """Return settings for a schema whose Nodes are the case-study registry."""
    registered = Settings(
        database_url=postgres_url,
        node_registry_path=ROOT / "fixtures" / "registry" / "nodes.csv",
        log_level="error",
    )
    organization = build_organization(registered)
    try:
        for command in read_node_registry(registered.node_registry_path):
            organization.register_node_handler.register(command)
    finally:
        organization.close()
    return registered


def _run(arguments: list[str], settings: Settings, capsys: pytest.CaptureFixture[str]) -> dict:  # type: ignore[type-arg]
    assert main(arguments, settings=settings) == EXIT_OK
    return json.loads(capsys.readouterr().out)  # type: ignore[no-any-return]


def _raise_riser_issue(settings: Settings, capsys: pytest.CaptureFixture[str]) -> dict:  # type: ignore[type-arg]
    return _run(
        [
            "raise",
            "--node",
            "platform_sp12",
            "--title",
            "Riser R-3 splash zone corrosion",
            "--description",
            "Gas export riser R-3 is losing wall in the splash zone.",
            "--domain",
            "asset integrity",
            "--tag",
            "riser",
            "--tag",
            "splash zone",
        ],
        settings,
        capsys,
    )


def test_cli_raises_a_new_issue_when_the_node_is_registered(
    settings: Settings, capsys: pytest.CaptureFixture[str]
):
    raised = _raise_riser_issue(settings, capsys)

    assert raised["status"] == "new"
    assert raised["owner_node_id"] == "platform_sp12"
    assert raised["metadata"]["tags"] == ["riser", "splash zone"]
    assert raised["sub_issues"] == []
    assert len(raised["issue_id"]) == 36


def test_cli_shows_and_lists_the_issue_when_it_was_raised(
    settings: Settings, capsys: pytest.CaptureFixture[str]
):
    raised = _raise_riser_issue(settings, capsys)

    shown = _run(["show", raised["issue_id"]], settings, capsys)
    listed = _run(["list", "--node", "platform_sp12"], settings, capsys)

    assert shown == raised
    assert listed["issues"] == [
        {
            "issue_id": raised["issue_id"],
            "title": "Riser R-3 splash zone corrosion",
            "status": "new",
            "raised_at": raised["raised_at"],
            "sub_issue_count": 0,
            "similar_issue_count": 0,
        }
    ]


def test_cli_flags_the_first_issue_when_the_same_problem_is_raised_again(
    settings: Settings, capsys: pytest.CaptureFixture[str]
):
    first = _raise_riser_issue(settings, capsys)

    again = _run(
        [
            "raise",
            "--node",
            "platform_sp12",
            "--title",
            "Splash zone corrosion on riser R-3",
            "--description",
            "Riser R-3 is losing wall in the splash zone.",
        ],
        settings,
        capsys,
    )
    shown = _run(["show", again["issue_id"]], settings, capsys)

    assert [(flag["issue_id"], flag["kind"]) for flag in again["similar_issues"]] == [
        (first["issue_id"], "duplicate")
    ]
    assert shown["similar_issues"] == again["similar_issues"]
    assert first["similar_issues"] == []


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        (
            ["raise", "--node", "platform_sp99", "--title", "T", "--description", "D"],
            "ISSUE_OWNER_NODE_NOT_FOUND",
        ),
        (
            ["raise", "--node", "platform_sp12", "--title", " ", "--description", "D"],
            "ISSUE_FIELD_EMPTY",
        ),
        (["show", "missing"], "ISSUE_NOT_FOUND"),
    ],
)
def test_cli_prints_problem_details_when_the_command_fails(
    settings: Settings, capsys: pytest.CaptureFixture[str], arguments: list[str], code: str
):
    assert main(arguments, settings=settings) == EXIT_FAILED

    problem = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert problem["type"] == code
