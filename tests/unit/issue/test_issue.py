from datetime import UTC, datetime
from typing import Any

import pytest

from offline_rag.issue.domain.errors import (
    InvalidSubIssuePositionError,
    IssueFieldEmptyError,
    SubIssueCycleError,
    SubIssueIdTakenError,
    SubIssueParentNotFoundError,
)
from offline_rag.issue.domain.events import IssueRaised
from offline_rag.issue.domain.issue import Issue
from offline_rag.issue.domain.issue_status import IssueStatus
from offline_rag.issue.domain.sub_issue import SubIssue
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

RAISED_AT = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)
OWNER = NodeIdentifier("platform_sp12")
ISSUE_ID = "riser-r3-corrosion"


def _raise(**changes: Any) -> Issue:
    values: dict[str, Any] = {
        "issue_id": ISSUE_ID,
        "owner_node_id": OWNER,
        "title": "Riser R-3 splash zone corrosion",
        "description": "Gas export riser R-3 is losing wall in the splash zone.",
        "metadata": MetadataRecord(domain="asset integrity"),
        "raised_at": RAISED_AT,
    }
    return Issue.raise_issue(**(values | changes))


def _sub(sub_issue_id: str, parent_id: str, position: int) -> SubIssue:
    return SubIssue(
        sub_issue_id=sub_issue_id,
        parent_id=parent_id,
        position=position,
        title=f"Title of {sub_issue_id}",
        description=f"Description of {sub_issue_id}",
        metadata=MetadataRecord(),
        status=IssueStatus.NEW,
    )


def _rebuild(sub_issues: list[SubIssue]) -> Issue:
    return Issue(
        issue_id=ISSUE_ID,
        owner_node_id=OWNER,
        title="Riser R-3 splash zone corrosion",
        description="Gas export riser R-3 is losing wall in the splash zone.",
        metadata=MetadataRecord(),
        status=IssueStatus.ANALYZING,
        raised_at=RAISED_AT,
        sub_issues=sub_issues,
    )


def _add(issue: Issue, sub_issue_id: str, parent_id: str = ISSUE_ID) -> SubIssue:
    return issue.add_sub_issue(
        sub_issue_id=sub_issue_id,
        parent_id=parent_id,
        title=f"Title of {sub_issue_id}",
        description=f"Description of {sub_issue_id}",
        metadata=MetadataRecord(),
    )


def test_new_issue_starts_as_new_with_no_sub_issues_when_raised():
    issue = _raise()

    assert issue.status == IssueStatus.NEW
    assert issue.owner_node_id == OWNER
    assert issue.raised_at == RAISED_AT
    assert issue.sub_issues == ()


def test_raised_event_is_recorded_once_when_issue_is_raised():
    issue = _raise()

    assert issue.pull_events() == (
        IssueRaised(occurred_at=RAISED_AT, issue_id=ISSUE_ID, owner_node_id=OWNER),
    )
    assert issue.pull_events() == ()


@pytest.mark.parametrize("field", ["issue_id", "title", "description"])
def test_issue_is_rejected_when_a_required_field_is_blank(field: str):
    with pytest.raises(IssueFieldEmptyError) as caught:
        _raise(**{field: "  "})

    assert caught.value.code == "ISSUE_FIELD_EMPTY"
    assert caught.value.details == {"field": field}


def test_sub_issues_are_numbered_in_order_when_added_under_one_parent():
    issue = _raise()

    for sub_issue_id in ("ut-survey", "growth-rate", "temporary-wrap"):
        _add(issue, sub_issue_id)

    children = issue.children_of(ISSUE_ID)
    assert [sub.sub_issue_id for sub in children] == ["ut-survey", "growth-rate", "temporary-wrap"]
    assert [sub.position for sub in children] == [1, 2, 3]
    assert all(sub.status == IssueStatus.NEW for sub in children)


def test_sub_issue_can_be_split_again_when_the_tree_grows():
    issue = _raise()
    _add(issue, "repair-option")

    sleeve = _add(issue, "sleeve", parent_id="repair-option")
    replacement = _add(issue, "replacement", parent_id="repair-option")

    assert [sub.sub_issue_id for sub in issue.children_of(ISSUE_ID)] == ["repair-option"]
    assert issue.children_of("repair-option") == (sleeve, replacement)
    assert (sleeve.position, replacement.position) == (1, 2)


def test_adding_a_sub_issue_records_no_event_when_the_issue_was_rebuilt():
    issue = _rebuild([])

    _add(issue, "ut-survey")

    assert issue.pull_events() == ()


@pytest.mark.parametrize("sub_issue_id", [ISSUE_ID, "ut-survey"])
def test_sub_issue_is_rejected_when_its_id_is_already_used(sub_issue_id: str):
    issue = _raise()
    _add(issue, "ut-survey")

    with pytest.raises(SubIssueIdTakenError) as caught:
        _add(issue, sub_issue_id)

    assert caught.value.code == "ISSUE_SUB_ISSUE_ID_TAKEN"
    assert len(issue.sub_issues) == 1


def test_sub_issue_is_rejected_when_its_parent_is_not_in_the_issue():
    issue = _raise()

    with pytest.raises(SubIssueParentNotFoundError) as caught:
        _add(issue, "ut-survey", parent_id="other-issue")

    assert caught.value.details == {
        "issue_id": ISSUE_ID,
        "sub_issue_id": "ut-survey",
        "parent_id": "other-issue",
    }
    assert issue.sub_issues == ()


@pytest.mark.parametrize("field", ["title", "description"])
def test_sub_issue_is_rejected_when_a_required_field_is_blank(field: str):
    issue = _raise()
    values = {"title": "UT survey", "description": "Rope access UT survey"} | {field: ""}

    with pytest.raises(IssueFieldEmptyError):
        issue.add_sub_issue(
            sub_issue_id="ut-survey", parent_id=ISSUE_ID, metadata=MetadataRecord(), **values
        )

    assert issue.sub_issues == ()


def test_stored_tree_is_kept_when_it_is_valid():
    issue = _rebuild(
        [_sub("sleeve", "repair", 1), _sub("repair", ISSUE_ID, 2), _sub("survey", ISSUE_ID, 1)]
    )

    assert [sub.sub_issue_id for sub in issue.children_of(ISSUE_ID)] == ["survey", "repair"]
    assert [sub.sub_issue_id for sub in issue.children_of("repair")] == ["sleeve"]


def test_stored_tree_is_rejected_when_two_sub_issues_share_an_id():
    with pytest.raises(SubIssueIdTakenError):
        _rebuild([_sub("survey", ISSUE_ID, 1), _sub("survey", ISSUE_ID, 2)])


def test_stored_tree_is_rejected_when_a_parent_is_missing():
    with pytest.raises(SubIssueParentNotFoundError):
        _rebuild([_sub("sleeve", "repair", 1)])


def test_stored_tree_is_rejected_when_sub_issues_form_a_cycle():
    with pytest.raises(SubIssueCycleError) as caught:
        _rebuild(
            [_sub("survey", ISSUE_ID, 1), _sub("sleeve", "repair", 1), _sub("repair", "sleeve", 1)]
        )

    assert caught.value.code == "ISSUE_SUB_ISSUE_CYCLE"
    assert caught.value.details == {"issue_id": ISSUE_ID, "sub_issue_ids": ["repair", "sleeve"]}


@pytest.mark.parametrize("positions", [[1, 3], [2], [1, 1], [0, 1]])
def test_stored_tree_is_rejected_when_sibling_positions_have_gaps(positions: list[int]):
    sub_issues = [
        _sub(f"sub-{index}", ISSUE_ID, position) for index, position in enumerate(positions)
    ]

    with pytest.raises(InvalidSubIssuePositionError) as caught:
        _rebuild(sub_issues)

    assert caught.value.details == {
        "issue_id": ISSUE_ID,
        "parent_id": ISSUE_ID,
        "positions": sorted(positions),
    }


def test_issues_are_equal_when_their_ids_match():
    assert _raise() == _rebuild([])
    assert len({_raise(), _rebuild([])}) == 1
    assert _raise() != _raise(issue_id="other-issue")


def test_sub_issue_keeps_its_fields_when_added():
    issue = _raise()
    metadata = MetadataRecord(tags=("splash zone",))

    added = issue.add_sub_issue(
        sub_issue_id="ut-survey",
        parent_id=ISSUE_ID,
        title="UT survey",
        description="Rope access UT survey of the splash zone",
        metadata=metadata,
    )

    assert (added.title, added.description, added.metadata) == (
        "UT survey",
        "Rope access UT survey of the splash zone",
        metadata,
    )
    assert (issue.title, issue.description) == (
        "Riser R-3 splash zone corrosion",
        "Gas export riser R-3 is losing wall in the splash zone.",
    )
    assert issue.metadata == MetadataRecord(domain="asset integrity")
    assert added == _sub("ut-survey", ISSUE_ID, 1)
    assert len({added, _sub("ut-survey", ISSUE_ID, 1)}) == 1
