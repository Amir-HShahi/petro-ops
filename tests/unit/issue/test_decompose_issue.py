from datetime import UTC, datetime

import pytest
from tests.fakes.issue import FakeIssueDecomposer, FakeKnowledgeReader, InMemoryIssueRepository

from offline_rag.issue.application.commands import DecomposeIssue
from offline_rag.issue.application.decompose_issue import DecomposeIssueHandler
from offline_rag.issue.application.errors import (
    IssueNotFoundError,
    KnowledgeItemNotFoundError,
    KnowledgeRequiredError,
)
from offline_rag.issue.application.ports import Decomposition, KnowledgePassage
from offline_rag.issue.domain.issue import Issue
from offline_rag.issue.domain.sub_issue_candidate import Citation, SubIssueCandidate
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

ISSUE_ID = "riser-r3"
PASSAGE = KnowledgePassage(
    item_id="ins-02-v2",
    page_or_section="4. Recommendation",
    text="Install a temporary splash zone wrap\nwithin 6 months. Reduce the survey interval.",
    token_count=20,
)


def _citation(quote: str, doc_id: str = "ins-02-v2") -> Citation:
    return Citation(doc_id=doc_id, page_or_section="4. Recommendation", quote=quote)


def _decomposition(*citations: Citation, missing: str | None = None) -> Decomposition:
    return Decomposition(
        candidates=(
            SubIssueCandidate(
                number=1,
                title="Temporary splash zone wrap",
                description="Wrap the splash zone until a repair is in place.",
                citations=citations,
            ),
            SubIssueCandidate(
                number=2,
                title="Reduced survey interval",
                description="Survey R-3 every 6 months until it is repaired.",
            ),
        ),
        missing_information=missing,
    )


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
    return InMemoryIssueRepository([issue])


def _handler(
    repository: InMemoryIssueRepository, decomposer: FakeIssueDecomposer
) -> DecomposeIssueHandler:
    return DecomposeIssueHandler(
        issue_repository=repository,
        knowledge_reader=FakeKnowledgeReader([PASSAGE]),
        decomposer=decomposer,
    )


def test_suggestions_are_stored_as_waiting_candidates_when_decomposed(
    repository: InMemoryIssueRepository,
):
    decomposer = FakeIssueDecomposer(_decomposition(missing="No repair cost estimate."))

    result = _handler(repository, decomposer).decompose(
        DecomposeIssue(issue_id=ISSUE_ID, knowledge_item_ids=("ins-02-v2",))
    )

    stored = repository.get_by_id(ISSUE_ID).sub_issue_candidates
    assert [candidate.title for candidate in stored] == [
        "Temporary splash zone wrap",
        "Reduced survey interval",
    ]
    assert result.candidates == stored
    assert result.missing_information == "No repair cost estimate."
    assert repository.get_by_id(ISSUE_ID).sub_issues == ()


def test_llm_reads_the_issue_and_the_named_knowledge_when_decomposing(
    repository: InMemoryIssueRepository,
):
    decomposer = FakeIssueDecomposer(_decomposition())

    _handler(repository, decomposer).decompose(
        DecomposeIssue(issue_id=ISSUE_ID, knowledge_item_ids=("ins-02-v2",))
    )

    assert decomposer.calls == [
        (
            "Riser R-3 splash zone corrosion",
            "Gas export riser R-3 is losing wall in the splash zone.",
            [PASSAGE],
        )
    ]


def test_only_citations_found_in_their_item_are_kept_when_decomposed(
    repository: InMemoryIssueRepository,
):
    found = _citation("install a temporary splash zone wrap within 6 months.")
    made_up = _citation("Replace the riser next week.")
    other_item = _citation("Reduce the survey interval.", doc_id="ins-01")
    decomposer = FakeIssueDecomposer(_decomposition(found, made_up, other_item))

    result = _handler(repository, decomposer).decompose(
        DecomposeIssue(issue_id=ISSUE_ID, knowledge_item_ids=("ins-02-v2",))
    )

    assert result.candidates[0].citations == (found,)
    assert result.dropped_citation_count == 2


def test_decomposition_is_refused_when_no_knowledge_is_named(
    repository: InMemoryIssueRepository,
):
    decomposer = FakeIssueDecomposer(_decomposition())

    with pytest.raises(KnowledgeRequiredError) as caught:
        _handler(repository, decomposer).decompose(
            DecomposeIssue(issue_id=ISSUE_ID, knowledge_item_ids=())
        )

    assert caught.value.code == "ISSUE_KNOWLEDGE_REQUIRED"
    assert decomposer.calls == []


@pytest.mark.parametrize(
    ("issue_id", "item_id", "error"),
    [
        ("missing", "ins-02-v2", IssueNotFoundError),
        (ISSUE_ID, "missing", KnowledgeItemNotFoundError),
    ],
)
def test_llm_is_not_asked_when_the_issue_or_an_item_is_missing(
    repository: InMemoryIssueRepository, issue_id: str, item_id: str, error: type[Exception]
):
    decomposer = FakeIssueDecomposer(_decomposition())

    with pytest.raises(error):
        _handler(repository, decomposer).decompose(
            DecomposeIssue(issue_id=issue_id, knowledge_item_ids=(item_id,))
        )

    assert decomposer.calls == []
