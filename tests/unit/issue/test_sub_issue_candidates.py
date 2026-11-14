from datetime import UTC, datetime

import pytest

from offline_rag.issue.domain.errors import (
    InvalidSubIssueCandidateError,
    IssueFieldEmptyError,
    SubIssueCandidateAlreadyAcceptedError,
    SubIssueCandidateNotFoundError,
)
from offline_rag.issue.domain.events import IssueDecomposed
from offline_rag.issue.domain.issue import Issue
from offline_rag.issue.domain.issue_status import IssueStatus
from offline_rag.issue.domain.sub_issue import SubIssue
from offline_rag.issue.domain.sub_issue_candidate import Citation, SubIssueCandidate
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

NOW = datetime(2026, 11, 14, 11, 0, tzinfo=UTC)
ISSUE_ID = "riser-r3"
CITATION = Citation(
    doc_id="ins-02-v2",
    page_or_section="4. Recommendation",
    quote="Install a temporary splash zone wrap within 6 months.",
)


def _candidate(title: str, number: int = 1, accepted: str | None = None) -> SubIssueCandidate:
    return SubIssueCandidate(
        number=number,
        title=title,
        description=f"Description of {title}",
        citations=(CITATION,),
        accepted_sub_issue_id=accepted,
    )


def _issue(
    candidates: list[SubIssueCandidate] | None = None, sub_issues: list[SubIssue] | None = None
) -> Issue:
    return Issue(
        issue_id=ISSUE_ID,
        owner_node_id=NodeIdentifier("platform_sp12"),
        title="Riser R-3 splash zone corrosion",
        description="Gas export riser R-3 is losing wall in the splash zone.",
        metadata=MetadataRecord(),
        status=IssueStatus.NEW,
        raised_at=NOW,
        sub_issues=sub_issues or [],
        sub_issue_candidates=candidates or [],
    )


@pytest.mark.parametrize(
    ("values", "field"),
    [
        ({"doc_id": " ", "page_or_section": "", "quote": "q"}, "citation_doc_id"),
        ({"doc_id": "ins-01", "page_or_section": "", "quote": ""}, "citation_quote"),
    ],
)
def test_citation_is_rejected_when_it_names_no_item_or_quotes_nothing(
    values: dict[str, str], field: str
):
    with pytest.raises(IssueFieldEmptyError) as caught:
        Citation(**values)

    assert caught.value.details == {"field": field}


@pytest.mark.parametrize(
    ("title", "description", "field"),
    [(" ", "D", "candidate_title"), ("T", "", "candidate_description")],
)
def test_candidate_is_rejected_when_a_text_is_blank(title: str, description: str, field: str):
    with pytest.raises(IssueFieldEmptyError) as caught:
        SubIssueCandidate(number=1, title=title, description=description)

    assert caught.value.details == {"field": field}


def test_candidates_are_numbered_in_order_when_proposed():
    issue = _issue()

    proposed = issue.propose_sub_issue_candidates(
        [_candidate("UT survey", 7), _candidate("Temporary wrap", 3)]
    )

    assert [(c.number, c.title) for c in proposed] == [(1, "UT survey"), (2, "Temporary wrap")]
    assert issue.sub_issue_candidates == proposed
    assert not any(candidate.is_accepted for candidate in proposed)


def test_waiting_candidates_are_replaced_and_accepted_ones_kept_when_proposed_again():
    issue = _issue(
        [_candidate("Accepted", 1, accepted="sub-1"), _candidate("Waiting", 2)],
        sub_issues=[_sub("sub-1")],
    )

    proposed = issue.propose_sub_issue_candidates([_candidate("New suggestion")])

    assert [(c.number, c.title) for c in issue.sub_issue_candidates] == [
        (1, "Accepted"),
        (3, "New suggestion"),
    ]
    assert proposed[0].number == 3


def _sub(sub_issue_id: str, position: int = 1) -> SubIssue:
    return SubIssue(
        sub_issue_id=sub_issue_id,
        parent_id=ISSUE_ID,
        position=position,
        title="Accepted",
        description="Description of Accepted",
        metadata=MetadataRecord(),
        status=IssueStatus.NEW,
    )


def test_chosen_candidates_become_sub_issues_in_the_given_order_when_accepted():
    issue = _issue([_candidate("UT survey", 1), _candidate("Wrap", 2), _candidate("Repair", 3)])

    accepted = issue.accept_sub_issue_candidates(
        numbers=[3, 1], sub_issue_ids=["sub-a", "sub-b"], accepted_at=NOW
    )

    assert [(sub.sub_issue_id, sub.title, sub.position) for sub in accepted] == [
        ("sub-a", "Repair", 1),
        ("sub-b", "UT survey", 2),
    ]
    assert issue.children_of(ISSUE_ID) == accepted
    assert [c.accepted_sub_issue_id for c in issue.sub_issue_candidates] == ["sub-b", None, "sub-a"]
    assert issue.pull_events() == (
        IssueDecomposed(occurred_at=NOW, issue_id=ISSUE_ID, sub_issue_ids=("sub-a", "sub-b")),
    )


def test_a_number_given_twice_is_accepted_once():
    issue = _issue([_candidate("UT survey", 1)])

    accepted = issue.accept_sub_issue_candidates(
        numbers=[1, 1], sub_issue_ids=["sub-a"], accepted_at=NOW
    )

    assert len(accepted) == 1


def test_nothing_changes_when_one_number_is_unknown():
    issue = _issue([_candidate("UT survey", 1)])

    with pytest.raises(SubIssueCandidateNotFoundError) as caught:
        issue.accept_sub_issue_candidates(
            numbers=[1, 9], sub_issue_ids=["sub-a", "sub-b"], accepted_at=NOW
        )

    assert caught.value.code == "ISSUE_SUB_ISSUE_CANDIDATE_NOT_FOUND"
    assert issue.sub_issues == ()
    assert not issue.sub_issue_candidates[0].is_accepted
    assert issue.pull_events() == ()


def test_candidate_is_refused_when_it_was_accepted_before():
    issue = _issue([_candidate("Accepted", 1, accepted="sub-1")], sub_issues=[_sub("sub-1")])

    with pytest.raises(SubIssueCandidateAlreadyAcceptedError) as caught:
        issue.accept_sub_issue_candidates(numbers=[1], sub_issue_ids=["sub-2"], accepted_at=NOW)

    assert caught.value.details == {"issue_id": ISSUE_ID, "number": 1, "sub_issue_id": "sub-1"}


@pytest.mark.parametrize(
    "candidates",
    [
        [_candidate("A", 1), _candidate("B", 1)],
        [_candidate("A", 0)],
        [_candidate("A", 1, accepted="not-a-sub-issue")],
    ],
    ids=["same number", "number zero", "lost sub-issue"],
)
def test_stored_candidates_are_rejected_when_they_break_a_rule(
    candidates: list[SubIssueCandidate],
):
    with pytest.raises(InvalidSubIssueCandidateError):
        _issue(candidates)
