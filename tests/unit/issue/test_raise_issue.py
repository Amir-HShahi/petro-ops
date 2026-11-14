from datetime import UTC, datetime
from typing import Any

import pytest
from tests.fakes.issue import InMemoryIssueRepository
from tests.fakes.knowledge import (
    FakeClock,
    FakeIdGenerator,
    FakeNodeDirectory,
    InMemoryEventPublisher,
)

from offline_rag.issue.application.commands import RaiseIssue
from offline_rag.issue.application.errors import IssueNotFoundError, OwnerNodeNotFoundError
from offline_rag.issue.application.issue_queries import IssueQueries
from offline_rag.issue.application.raise_issue import RaiseIssueHandler
from offline_rag.issue.domain.errors import IssueFieldEmptyError
from offline_rag.issue.domain.events import IssueRaised, SimilarIssueFound
from offline_rag.issue.domain.issue_status import IssueStatus
from offline_rag.issue.domain.similar_issue import SimilarIssueDetector, SimilarIssueKind
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

NOW = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)
PLATFORM = NodeIdentifier("platform_sp12")


def _command(**changes: Any) -> RaiseIssue:
    values: dict[str, Any] = {
        "owner_node_id": PLATFORM,
        "title": "Riser R-3 splash zone corrosion",
        "description": "Gas export riser R-3 is losing wall in the splash zone.",
        "metadata": MetadataRecord(domain="asset integrity", tags=("riser",)),
    }
    return RaiseIssue(**(values | changes))


@pytest.fixture
def repository() -> InMemoryIssueRepository:
    return InMemoryIssueRepository()


@pytest.fixture
def publisher() -> InMemoryEventPublisher:
    return InMemoryEventPublisher()


@pytest.fixture
def handler(
    repository: InMemoryIssueRepository, publisher: InMemoryEventPublisher
) -> RaiseIssueHandler:
    return RaiseIssueHandler(
        issue_repository=repository,
        node_directory=FakeNodeDirectory(["platform_sp12", "sp12_inspection_team"]),
        clock=FakeClock(NOW),
        id_generator=FakeIdGenerator("issue"),
        event_publisher=publisher,
        detector=SimilarIssueDetector(duplicate_from=0.40, overlap_from=0.25),
    )


def test_issue_is_stored_as_new_when_raised_for_a_registered_node(
    handler: RaiseIssueHandler, repository: InMemoryIssueRepository
):
    issue = handler.raise_issue(_command())

    stored = repository.get_by_id("issue-1")
    assert stored is issue
    assert stored.status == IssueStatus.NEW
    assert stored.raised_at == NOW
    assert stored.metadata == MetadataRecord(domain="asset integrity", tags=("riser",))


def test_raised_event_is_published_when_issue_is_stored(
    handler: RaiseIssueHandler, publisher: InMemoryEventPublisher
):
    handler.raise_issue(_command())

    assert publisher.events == [
        IssueRaised(occurred_at=NOW, issue_id="issue-1", owner_node_id=PLATFORM)
    ]


def test_each_issue_gets_its_own_id_when_several_are_raised(handler: RaiseIssueHandler):
    first = handler.raise_issue(_command())
    second = handler.raise_issue(_command(title="Gas compressor vibration"))

    assert (first.issue_id, second.issue_id) == ("issue-1", "issue-2")


def test_issue_is_rejected_when_its_node_is_not_registered(
    handler: RaiseIssueHandler,
    repository: InMemoryIssueRepository,
    publisher: InMemoryEventPublisher,
):
    with pytest.raises(OwnerNodeNotFoundError) as caught:
        handler.raise_issue(_command(owner_node_id=NodeIdentifier("platform_sp99")))

    assert caught.value.code == "ISSUE_OWNER_NODE_NOT_FOUND"
    assert caught.value.details == {"node_id": "platform_sp99"}
    assert repository.issues == {}
    assert publisher.events == []


def test_nothing_is_stored_when_the_title_is_blank(
    handler: RaiseIssueHandler,
    repository: InMemoryIssueRepository,
    publisher: InMemoryEventPublisher,
):
    with pytest.raises(IssueFieldEmptyError):
        handler.raise_issue(_command(title=" "))

    assert repository.issues == {}
    assert publisher.events == []


def test_queries_list_only_the_issues_of_one_node_when_asked(
    handler: RaiseIssueHandler, repository: InMemoryIssueRepository
):
    handler.raise_issue(_command())
    handler.raise_issue(_command(owner_node_id=NodeIdentifier("sp12_inspection_team")))
    queries = IssueQueries(issue_repository=repository)

    assert [issue.issue_id for issue in queries.list_by_owner(PLATFORM)] == ["issue-1"]
    assert queries.get("issue-2").owner_node_id == NodeIdentifier("sp12_inspection_team")


def test_queries_raise_not_found_when_the_id_is_unknown(repository: InMemoryIssueRepository):
    with pytest.raises(IssueNotFoundError) as caught:
        IssueQueries(issue_repository=repository).get("missing")

    assert caught.value.code == "ISSUE_NOT_FOUND"


def test_similar_issue_of_the_node_is_flagged_when_a_new_issue_repeats_it(
    handler: RaiseIssueHandler, publisher: InMemoryEventPublisher
):
    handler.raise_issue(_command())
    handler.raise_issue(_command(owner_node_id=NodeIdentifier("sp12_inspection_team")))

    repeated = handler.raise_issue(
        _command(
            title="Splash zone corrosion on riser R-3",
            description="Riser R-3 is losing wall in the splash zone.",
        )
    )

    [flag] = repeated.similar_issue_flags
    assert (flag.similar_issue_id, flag.kind) == ("issue-1", SimilarIssueKind.DUPLICATE)
    assert publisher.events[-1] == SimilarIssueFound(
        occurred_at=NOW,
        issue_id="issue-3",
        similar_issue_id="issue-1",
        kind=SimilarIssueKind.DUPLICATE,
        score=flag.score,
    )


def test_no_issue_is_flagged_when_the_new_one_is_about_something_else(
    handler: RaiseIssueHandler, publisher: InMemoryEventPublisher
):
    handler.raise_issue(_command())

    other = handler.raise_issue(
        _command(
            title="Gas compressor K-101 vibration",
            description="Vibration on compressor K-101 rose above the alarm level.",
        )
    )

    assert other.similar_issue_flags == ()
    assert [type(event) for event in publisher.events] == [IssueRaised, IssueRaised]
