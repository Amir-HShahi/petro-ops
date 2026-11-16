"""The six T16 handlers load the Issue, change it, save it and publish its events."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from tests.fakes.issue import InMemoryIssueRepository
from tests.fakes.knowledge import FakeClock, InMemoryEventPublisher

from offline_rag.issue.application.add_sub_issue_dependency import AddSubIssueDependencyHandler
from offline_rag.issue.application.change_issue_status import ChangeIssueStatusHandler
from offline_rag.issue.application.commands import (
    AddSubIssueDependency,
    ChangeIssueStatus,
    MoveSubIssue,
    RemoveSubIssueDependency,
    ResolveIssue,
    SetIssuePriority,
)
from offline_rag.issue.application.errors import IssueNotFoundError
from offline_rag.issue.application.move_sub_issue import MoveSubIssueHandler
from offline_rag.issue.application.remove_sub_issue_dependency import (
    RemoveSubIssueDependencyHandler,
)
from offline_rag.issue.application.resolve_issue import ResolveIssueHandler
from offline_rag.issue.application.set_issue_priority import SetIssuePriorityHandler
from offline_rag.issue.domain.events import (
    IssuePrioritized,
    IssueResolved,
    IssueStatusChanged,
    SubIssueDependencyAdded,
    SubIssueDependencyRemoved,
    SubIssueMoved,
)
from offline_rag.issue.domain.issue import Issue
from offline_rag.issue.domain.issue_priority import IssuePriority
from offline_rag.issue.domain.issue_status import IssueStatus
from offline_rag.issue.domain.sub_issue import SubIssue
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

NOW = datetime(2026, 11, 14, 14, 0, tzinfo=UTC)
ISSUE_ID = "riser-r3"


def _sub(sub_issue_id: str, position: int, **changes: Any) -> SubIssue:
    values: dict[str, Any] = {
        "sub_issue_id": sub_issue_id,
        "parent_id": ISSUE_ID,
        "position": position,
        "title": f"Title of {sub_issue_id}",
        "description": f"Description of {sub_issue_id}",
        "metadata": MetadataRecord(),
        "status": IssueStatus.NEW,
    }
    return SubIssue(**(values | changes))


def _repository(*sub_issues: SubIssue) -> InMemoryIssueRepository:
    return InMemoryIssueRepository(
        [
            Issue(
                issue_id=ISSUE_ID,
                owner_node_id=NodeIdentifier("platform_sp12"),
                title="Riser R-3 splash zone corrosion",
                description="Gas export riser R-3 is losing wall in the splash zone.",
                metadata=MetadataRecord(),
                status=IssueStatus.ANALYZING,
                raised_at=NOW,
                sub_issues=list(sub_issues),
            )
        ]
    )


Case = tuple[type, str, Any, list[SubIssue], type, Callable[[Issue], bool]]

CASES: list[Case] = [
    (
        SetIssuePriorityHandler,
        "set_priority",
        SetIssuePriority(issue_id=ISSUE_ID, priority=IssuePriority.CRITICAL),
        [],
        IssuePrioritized,
        lambda issue: issue.priority == IssuePriority.CRITICAL,
    ),
    (
        MoveSubIssueHandler,
        "move",
        MoveSubIssue(issue_id=ISSUE_ID, sub_issue_id="wrap", position=1),
        [_sub("survey", 1), _sub("wrap", 2)],
        SubIssueMoved,
        lambda issue: issue.children_of(ISSUE_ID)[0].sub_issue_id == "wrap",
    ),
    (
        AddSubIssueDependencyHandler,
        "add",
        AddSubIssueDependency(
            issue_id=ISSUE_ID, sub_issue_id="wrap", depends_on_sub_issue_id="survey"
        ),
        [_sub("survey", 1), _sub("wrap", 2)],
        SubIssueDependencyAdded,
        lambda issue: issue.children_of(ISSUE_ID)[1].depends_on == ("survey",),
    ),
    (
        RemoveSubIssueDependencyHandler,
        "remove",
        RemoveSubIssueDependency(
            issue_id=ISSUE_ID, sub_issue_id="wrap", depends_on_sub_issue_id="survey"
        ),
        [_sub("survey", 1), _sub("wrap", 2, depends_on=("survey",))],
        SubIssueDependencyRemoved,
        lambda issue: issue.children_of(ISSUE_ID)[1].depends_on == (),
    ),
    (
        ChangeIssueStatusHandler,
        "change",
        ChangeIssueStatus(issue_id=ISSUE_ID, status=IssueStatus.ARCHIVED, sub_issue_id="survey"),
        [_sub("survey", 1)],
        IssueStatusChanged,
        lambda issue: issue.sub_issues[0].status == IssueStatus.ARCHIVED,
    ),
    (
        ResolveIssueHandler,
        "resolve",
        ResolveIssue(issue_id=ISSUE_ID, resolution_summary="Section replaced."),
        [_sub("survey", 1, status=IssueStatus.RESOLVED)],
        IssueResolved,
        lambda issue: issue.resolution_summary == "Section replaced.",
    ),
]
IDS = ["priority", "move", "add dependency", "remove dependency", "status", "resolve"]


@pytest.mark.parametrize(
    ("handler_class", "method", "command", "subs", "event", "check"), CASES, ids=IDS
)
def test_change_is_saved_and_announced_when_the_handler_runs(
    handler_class: type,
    method: str,
    command: Any,
    subs: list[SubIssue],
    event: type,
    check: Callable[[Issue], bool],
):
    repository = _repository(*subs)
    publisher = InMemoryEventPublisher()
    handler = handler_class(
        issue_repository=repository, clock=FakeClock(NOW), event_publisher=publisher
    )

    returned = getattr(handler, method)(command)

    assert returned is repository.get_by_id(ISSUE_ID)
    assert check(repository.get_by_id(ISSUE_ID))
    assert isinstance(publisher.events[-1], event)
    assert publisher.events[-1].occurred_at == NOW


@pytest.mark.parametrize(
    ("handler_class", "method", "command", "subs", "event", "check"), CASES, ids=IDS
)
def test_nothing_is_published_when_the_issue_does_not_exist(
    handler_class: type,
    method: str,
    command: Any,
    subs: list[SubIssue],
    event: type,
    check: Callable[[Issue], bool],
):
    publisher = InMemoryEventPublisher()
    handler = handler_class(
        issue_repository=InMemoryIssueRepository(), clock=FakeClock(NOW), event_publisher=publisher
    )

    with pytest.raises(IssueNotFoundError):
        getattr(handler, method)(command)

    assert publisher.events == []
