from datetime import UTC, datetime
from typing import Any

import pytest
from tests.fakes.issue import InMemoryIssueRepository
from tests.fakes.knowledge import FakeClock, FakeIdGenerator, InMemoryEventPublisher

from offline_rag.issue.application.add_sub_issue import AddSubIssueHandler
from offline_rag.issue.application.commands import AddSubIssue
from offline_rag.issue.application.errors import IssueNotFoundError
from offline_rag.issue.domain.errors import IssueFieldEmptyError, SubIssueParentNotFoundError
from offline_rag.issue.domain.events import SubIssueAdded
from offline_rag.issue.domain.issue import Issue
from offline_rag.issue.domain.issue_status import IssueStatus
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

NOW = datetime(2026, 11, 14, 10, 0, tzinfo=UTC)
ISSUE_ID = "riser-r3"


def _command(**changes: Any) -> AddSubIssue:
    values: dict[str, Any] = {
        "issue_id": ISSUE_ID,
        "parent_id": None,
        "title": "Rope access UT survey of the splash zone",
        "description": "Measure the remaining wall between EL +5 m and EL +9 m.",
        "metadata": MetadataRecord(tags=("ut",)),
    }
    return AddSubIssue(**(values | changes))


@pytest.fixture
def repository() -> InMemoryIssueRepository:
    issue = Issue.raise_issue(
        issue_id=ISSUE_ID,
        owner_node_id=NodeIdentifier("platform_sp12"),
        title="Riser R-3 splash zone corrosion",
        description="Gas export riser R-3 is losing wall in the splash zone.",
        metadata=MetadataRecord(),
        raised_at=datetime(2026, 11, 14, 9, 0, tzinfo=UTC),
    )
    issue.pull_events()
    return InMemoryIssueRepository([issue])


@pytest.fixture
def publisher() -> InMemoryEventPublisher:
    return InMemoryEventPublisher()


@pytest.fixture
def handler(
    repository: InMemoryIssueRepository, publisher: InMemoryEventPublisher
) -> AddSubIssueHandler:
    return AddSubIssueHandler(
        issue_repository=repository,
        clock=FakeClock(NOW),
        id_generator=FakeIdGenerator("sub"),
        event_publisher=publisher,
    )


def test_sub_issue_is_stored_under_the_issue_when_no_parent_is_given(
    handler: AddSubIssueHandler, repository: InMemoryIssueRepository
):
    _, added = handler.add_sub_issue(_command())

    [stored] = repository.get_by_id(ISSUE_ID).children_of(ISSUE_ID)
    assert stored is added
    assert (added.sub_issue_id, added.position, added.status) == ("sub-1", 1, IssueStatus.NEW)
    assert added.metadata == MetadataRecord(tags=("ut",))


def test_sub_issue_is_split_further_when_a_sub_issue_is_the_parent(
    handler: AddSubIssueHandler, repository: InMemoryIssueRepository
):
    handler.add_sub_issue(_command(title="Repair option"))

    handler.add_sub_issue(_command(parent_id="sub-1", title="Clamp-on sleeve"))
    issue, added = handler.add_sub_issue(_command(parent_id="sub-1", title="Section replacement"))

    assert [sub.title for sub in issue.children_of("sub-1")] == [
        "Clamp-on sleeve",
        "Section replacement",
    ]
    assert (added.parent_id, added.position) == ("sub-1", 2)
    assert repository.get_by_id(ISSUE_ID) is issue


def test_added_event_is_published_when_the_sub_issue_is_stored(
    handler: AddSubIssueHandler, publisher: InMemoryEventPublisher
):
    handler.add_sub_issue(_command())

    assert publisher.events == [
        SubIssueAdded(
            occurred_at=NOW, issue_id=ISSUE_ID, sub_issue_id="sub-1", parent_id=ISSUE_ID, position=1
        )
    ]


def test_sub_issue_is_rejected_when_the_issue_does_not_exist(
    handler: AddSubIssueHandler, publisher: InMemoryEventPublisher
):
    with pytest.raises(IssueNotFoundError):
        handler.add_sub_issue(_command(issue_id="missing"))

    assert publisher.events == []


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"parent_id": "sub-99"}, SubIssueParentNotFoundError),
        ({"title": " "}, IssueFieldEmptyError),
    ],
)
def test_nothing_is_stored_when_the_sub_issue_breaks_a_rule(
    handler: AddSubIssueHandler,
    repository: InMemoryIssueRepository,
    publisher: InMemoryEventPublisher,
    changes: dict[str, Any],
    error: type[Exception],
):
    with pytest.raises(error):
        handler.add_sub_issue(_command(**changes))

    assert repository.get_by_id(ISSUE_ID).sub_issues == ()
    assert publisher.events == []
