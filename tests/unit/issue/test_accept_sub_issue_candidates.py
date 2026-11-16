from datetime import UTC, datetime

import pytest
from tests.fakes.issue import InMemoryIssueRepository
from tests.fakes.knowledge import FakeClock, FakeIdGenerator, InMemoryEventPublisher

from offline_rag.issue.application.accept_sub_issue_candidates import (
    AcceptSubIssueCandidatesHandler,
)
from offline_rag.issue.application.commands import AcceptSubIssueCandidates
from offline_rag.issue.application.errors import IssueNotFoundError
from offline_rag.issue.domain.errors import SubIssueCandidateNotFoundError
from offline_rag.issue.domain.events import IssueDecomposed
from offline_rag.issue.domain.issue import Issue
from offline_rag.issue.domain.sub_issue_candidate import SubIssueCandidate
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
ISSUE_ID = "riser-r3"


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
    issue.propose_sub_issue_candidates(
        [
            SubIssueCandidate(number=1, title="UT survey", description="Survey the wall."),
            SubIssueCandidate(number=2, title="Temporary wrap", description="Wrap the zone."),
        ]
    )
    issue.pull_events()
    return InMemoryIssueRepository([issue])


@pytest.fixture
def publisher() -> InMemoryEventPublisher:
    return InMemoryEventPublisher()


@pytest.fixture
def handler(
    repository: InMemoryIssueRepository, publisher: InMemoryEventPublisher
) -> AcceptSubIssueCandidatesHandler:
    return AcceptSubIssueCandidatesHandler(
        issue_repository=repository,
        clock=FakeClock(NOW),
        id_generator=FakeIdGenerator("sub"),
        event_publisher=publisher,
    )


def test_chosen_candidates_are_stored_as_sub_issues_when_accepted(
    handler: AcceptSubIssueCandidatesHandler,
    repository: InMemoryIssueRepository,
    publisher: InMemoryEventPublisher,
):
    handler.accept(AcceptSubIssueCandidates(issue_id=ISSUE_ID, numbers=(2, 2, 1)))

    stored = repository.get_by_id(ISSUE_ID)
    assert [(sub.sub_issue_id, sub.title) for sub in stored.children_of(ISSUE_ID)] == [
        ("sub-1", "Temporary wrap"),
        ("sub-2", "UT survey"),
    ]
    assert publisher.events == [
        IssueDecomposed(occurred_at=NOW, issue_id=ISSUE_ID, sub_issue_ids=("sub-1", "sub-2"))
    ]


@pytest.mark.parametrize(
    ("command", "error"),
    [
        (AcceptSubIssueCandidates(issue_id="missing", numbers=(1,)), IssueNotFoundError),
        (AcceptSubIssueCandidates(issue_id=ISSUE_ID, numbers=(5,)), SubIssueCandidateNotFoundError),
    ],
)
def test_nothing_is_published_when_the_issue_or_a_candidate_is_missing(
    handler: AcceptSubIssueCandidatesHandler,
    publisher: InMemoryEventPublisher,
    command: AcceptSubIssueCandidates,
    error: type[Exception],
):
    with pytest.raises(error):
        handler.accept(command)

    assert publisher.events == []
