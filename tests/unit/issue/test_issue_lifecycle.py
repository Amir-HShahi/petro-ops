from datetime import UTC, datetime

import pytest

from offline_rag.issue.domain.errors import (
    ArchivedIsFinalError,
    IssueClosedError,
    IssueFieldEmptyError,
    IssueHasOpenSubIssuesError,
    ResolveIssueRequiredError,
    SubIssueDependencyCycleError,
    SubIssueDependencyNotFoundError,
    SubIssueNotFoundError,
    SubIssuePositionOutOfRangeError,
)
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
from offline_rag.issue.domain.sub_issue_candidate import SubIssueCandidate
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

NOW = datetime(2026, 11, 14, 13, 0, tzinfo=UTC)
ISSUE_ID = "riser-r3"
OWNER = NodeIdentifier("platform_sp12")


def _sub(
    sub_issue_id: str,
    position: int,
    *,
    parent_id: str = ISSUE_ID,
    status: IssueStatus = IssueStatus.NEW,
    depends_on: tuple[str, ...] = (),
) -> SubIssue:
    return SubIssue(
        sub_issue_id=sub_issue_id,
        parent_id=parent_id,
        position=position,
        title=f"Title of {sub_issue_id}",
        description=f"Description of {sub_issue_id}",
        metadata=MetadataRecord(),
        status=status,
        depends_on=depends_on,
    )


def _issue(
    sub_issues: list[SubIssue] | None = None,
    *,
    status: IssueStatus = IssueStatus.ANALYZING,
    resolution_summary: str | None = None,
) -> Issue:
    return Issue(
        issue_id=ISSUE_ID,
        owner_node_id=OWNER,
        title="Riser R-3 splash zone corrosion",
        description="Gas export riser R-3 is losing wall in the splash zone.",
        metadata=MetadataRecord(),
        status=status,
        raised_at=NOW,
        sub_issues=sub_issues or [],
        resolution_summary=resolution_summary,
    )


def _survey_wrap_repair() -> Issue:
    return _issue([_sub("survey", 1), _sub("wrap", 2), _sub("repair", 3)])


def _order(issue: Issue, parent_id: str = ISSUE_ID) -> list[str]:
    return [sub.sub_issue_id for sub in issue.children_of(parent_id)]


def test_priority_is_set_and_announced_when_it_changes():
    issue = _issue()

    issue.set_priority(IssuePriority.HIGH, set_at=NOW)
    issue.set_priority(IssuePriority.HIGH, set_at=NOW)

    assert issue.priority == IssuePriority.HIGH
    assert issue.pull_events() == (
        IssuePrioritized(occurred_at=NOW, issue_id=ISSUE_ID, priority=IssuePriority.HIGH),
    )


@pytest.mark.parametrize(
    ("sub_issue_id", "position", "order"),
    [
        ("repair", 1, ["repair", "survey", "wrap"]),
        ("survey", 3, ["wrap", "repair", "survey"]),
        ("wrap", 1, ["wrap", "survey", "repair"]),
    ],
)
def test_siblings_move_along_when_a_sub_issue_moves(
    sub_issue_id: str, position: int, order: list[str]
):
    issue = _survey_wrap_repair()

    issue.move_sub_issue(sub_issue_id, position=position, moved_at=NOW)

    assert _order(issue) == order
    assert [sub.position for sub in issue.children_of(ISSUE_ID)] == [1, 2, 3]
    assert issue.pull_events() == (
        SubIssueMoved(
            occurred_at=NOW, issue_id=ISSUE_ID, sub_issue_id=sub_issue_id, position=position
        ),
    )


def test_only_the_siblings_change_place_when_a_nested_sub_issue_moves():
    issue = _issue(
        [
            _sub("survey", 1),
            _sub("repair", 2),
            _sub("sleeve", 1, parent_id="repair"),
            _sub("replace", 2, parent_id="repair"),
        ]
    )

    issue.move_sub_issue("replace", position=1, moved_at=NOW)

    assert _order(issue, "repair") == ["replace", "sleeve"]
    assert _order(issue) == ["survey", "repair"]


def test_nothing_is_recorded_when_a_sub_issue_stays_in_its_place():
    issue = _survey_wrap_repair()

    issue.move_sub_issue("wrap", position=2, moved_at=NOW)

    assert issue.pull_events() == ()


@pytest.mark.parametrize("position", [0, 4])
def test_move_is_refused_when_the_place_does_not_exist(position: int):
    issue = _survey_wrap_repair()

    with pytest.raises(SubIssuePositionOutOfRangeError) as caught:
        issue.move_sub_issue("wrap", position=position, moved_at=NOW)

    assert caught.value.details == {
        "sub_issue_id": "wrap",
        "position": position,
        "sibling_count": 3,
    }
    assert _order(issue) == ["survey", "wrap", "repair"]


def test_move_is_refused_when_the_sub_issue_does_not_exist():
    with pytest.raises(SubIssueNotFoundError) as caught:
        _survey_wrap_repair().move_sub_issue("missing", position=1, moved_at=NOW)

    assert caught.value.code == "ISSUE_SUB_ISSUE_NOT_FOUND"


def test_dependency_is_recorded_once_when_added_twice():
    issue = _survey_wrap_repair()

    issue.add_sub_issue_dependency("repair", depends_on_sub_issue_id="survey", added_at=NOW)
    issue.add_sub_issue_dependency("repair", depends_on_sub_issue_id="survey", added_at=NOW)

    [repair] = [sub for sub in issue.sub_issues if sub.sub_issue_id == "repair"]
    assert repair.depends_on == ("survey",)
    assert issue.pull_events() == (
        SubIssueDependencyAdded(
            occurred_at=NOW,
            issue_id=ISSUE_ID,
            sub_issue_id="repair",
            depends_on_sub_issue_id="survey",
        ),
    )


@pytest.mark.parametrize(
    ("waiting", "on", "cycle"),
    [
        ("survey", "survey", ["survey"]),
        ("survey", "repair", ["repair", "survey", "wrap"]),
    ],
    ids=["itself", "through another"],
)
def test_dependency_is_refused_when_sub_issues_would_wait_for_each_other(
    waiting: str, on: str, cycle: list[str]
):
    issue = _survey_wrap_repair()
    issue.add_sub_issue_dependency("repair", depends_on_sub_issue_id="wrap", added_at=NOW)
    issue.add_sub_issue_dependency("wrap", depends_on_sub_issue_id="survey", added_at=NOW)
    issue.pull_events()

    with pytest.raises(SubIssueDependencyCycleError) as caught:
        issue.add_sub_issue_dependency(waiting, depends_on_sub_issue_id=on, added_at=NOW)

    assert caught.value.details == {"issue_id": ISSUE_ID, "sub_issue_ids": cycle}
    assert issue.pull_events() == ()


def test_dependency_is_refused_when_the_other_sub_issue_does_not_exist():
    with pytest.raises(SubIssueNotFoundError):
        _survey_wrap_repair().add_sub_issue_dependency(
            "repair", depends_on_sub_issue_id="missing", added_at=NOW
        )


def test_dependency_is_gone_and_announced_when_removed():
    issue = _issue([_sub("survey", 1), _sub("repair", 2, depends_on=("survey",))])

    issue.remove_sub_issue_dependency("repair", depends_on_sub_issue_id="survey", removed_at=NOW)

    assert all(sub.depends_on == () for sub in issue.sub_issues)
    assert issue.pull_events() == (
        SubIssueDependencyRemoved(
            occurred_at=NOW,
            issue_id=ISSUE_ID,
            sub_issue_id="repair",
            depends_on_sub_issue_id="survey",
        ),
    )


def test_removing_is_refused_when_the_sub_issue_does_not_wait_for_the_other():
    with pytest.raises(SubIssueDependencyNotFoundError):
        _survey_wrap_repair().remove_sub_issue_dependency(
            "repair", depends_on_sub_issue_id="survey", removed_at=NOW
        )


@pytest.mark.parametrize(
    ("sub_issues", "error"),
    [
        ([_sub("survey", 1, depends_on=("missing",))], SubIssueNotFoundError),
        (
            [_sub("survey", 1, depends_on=("wrap",)), _sub("wrap", 2, depends_on=("survey",))],
            SubIssueDependencyCycleError,
        ),
    ],
    ids=["unknown", "cycle"],
)
def test_stored_dependencies_are_rejected_when_they_break_a_rule(
    sub_issues: list[SubIssue], error: type[Exception]
):
    with pytest.raises(error):
        _issue(sub_issues)


def test_issue_status_change_is_announced_with_the_previous_status():
    issue = _issue()

    issue.change_status(IssueStatus.IN_EXECUTION, changed_at=NOW)
    issue.change_status(IssueStatus.IN_EXECUTION, changed_at=NOW)

    assert issue.status == IssueStatus.IN_EXECUTION
    assert issue.pull_events() == (
        IssueStatusChanged(
            occurred_at=NOW,
            issue_id=ISSUE_ID,
            sub_issue_id=None,
            previous_status=IssueStatus.ANALYZING,
            status=IssueStatus.IN_EXECUTION,
        ),
    )


def test_sub_issue_status_change_names_the_sub_issue_when_announced():
    issue = _survey_wrap_repair()

    issue.change_status(IssueStatus.RESOLVED, changed_at=NOW, sub_issue_id="wrap")

    assert {sub.sub_issue_id: sub.status for sub in issue.sub_issues}[
        "wrap"
    ] == IssueStatus.RESOLVED
    assert issue.status == IssueStatus.ANALYZING
    [event] = issue.pull_events()
    assert isinstance(event, IssueStatusChanged)
    assert (event.sub_issue_id, event.status) == ("wrap", IssueStatus.RESOLVED)


def test_issue_is_refused_resolved_status_when_set_directly():
    with pytest.raises(ResolveIssueRequiredError):
        _issue().change_status(IssueStatus.RESOLVED, changed_at=NOW)


@pytest.mark.parametrize("sub_issue_id", [None, "survey"])
def test_archived_status_is_kept_when_another_is_given(sub_issue_id: str | None):
    issue = _issue([_sub("survey", 1, status=IssueStatus.ARCHIVED)])
    if sub_issue_id is None:
        issue.change_status(IssueStatus.ARCHIVED, changed_at=NOW)

    with pytest.raises(ArchivedIsFinalError):
        issue.change_status(IssueStatus.ANALYZING, changed_at=NOW, sub_issue_id=sub_issue_id)


def test_issue_is_refused_resolving_when_a_sub_issue_is_open():
    issue = _issue([_sub("survey", 1, status=IssueStatus.RESOLVED), _sub("wrap", 2)])

    with pytest.raises(IssueHasOpenSubIssuesError) as caught:
        issue.resolve("Wrap installed and section replaced.", resolved_at=NOW)

    assert caught.value.details == {"issue_id": ISSUE_ID, "sub_issue_ids": ["wrap"]}
    assert issue.status == IssueStatus.ANALYZING


def test_resolution_is_kept_and_announced_when_every_sub_issue_is_closed():
    issue = _issue(
        [
            _sub("survey", 1, status=IssueStatus.RESOLVED),
            _sub("wrap", 2, status=IssueStatus.UNRESOLVED),
            _sub("repair", 3, status=IssueStatus.ARCHIVED),
        ]
    )

    issue.resolve("Section replaced in March.", resolved_at=NOW)

    assert (issue.status, issue.resolution_summary) == (
        IssueStatus.RESOLVED,
        "Section replaced in March.",
    )
    assert issue.pull_events()[-1] == IssueResolved(
        occurred_at=NOW,
        issue_id=ISSUE_ID,
        owner_node_id=OWNER,
        resolution_summary="Section replaced in March.",
    )


def test_resolution_is_refused_when_the_summary_is_blank():
    with pytest.raises(IssueFieldEmptyError) as caught:
        _issue().resolve("  ", resolved_at=NOW)

    assert caught.value.details == {"field": "resolution_summary"}


def test_reopening_a_resolved_issue_drops_its_resolution():
    issue = _issue()
    issue.resolve("Section replaced.", resolved_at=NOW)

    issue.change_status(IssueStatus.ANALYZING, changed_at=NOW)

    assert issue.resolution_summary is None
    assert not issue.is_closed


@pytest.mark.parametrize(
    "change",
    [
        lambda issue: issue.set_priority(IssuePriority.LOW, set_at=NOW),
        lambda issue: issue.move_sub_issue("survey", position=1, moved_at=NOW),
        lambda issue: issue.add_sub_issue_dependency(
            "survey", depends_on_sub_issue_id="survey", added_at=NOW
        ),
        lambda issue: issue.change_status(
            IssueStatus.ANALYZING, changed_at=NOW, sub_issue_id="survey"
        ),
        lambda issue: issue.add_sub_issue(
            sub_issue_id="new",
            parent_id=ISSUE_ID,
            title="T",
            description="D",
            metadata=MetadataRecord(),
            added_at=NOW,
        ),
        lambda issue: issue.propose_sub_issue_candidates(
            [SubIssueCandidate(number=1, title="T", description="D")]
        ),
        lambda issue: issue.resolve("Again.", resolved_at=NOW),
    ],
    ids=["priority", "move", "dependency", "sub status", "sub issue", "candidates", "resolve"],
)
def test_closed_issue_refuses_changes_when_it_is_resolved(change):  # type: ignore[no-untyped-def]
    issue = _issue([_sub("survey", 1, status=IssueStatus.RESOLVED)])
    issue.resolve("Section replaced.", resolved_at=NOW)

    with pytest.raises(IssueClosedError) as caught:
        change(issue)

    assert caught.value.details == {"issue_id": ISSUE_ID, "status": "resolved"}


def test_stored_issue_is_rejected_when_resolved_without_a_summary():
    with pytest.raises(IssueFieldEmptyError):
        _issue(status=IssueStatus.RESOLVED)


def test_resolution_is_dropped_when_a_stored_issue_is_not_resolved():
    assert _issue(resolution_summary="Old summary.").resolution_summary is None
