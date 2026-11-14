"""In-memory fakes of the Issue Management ports, for unit tests.

`FakeClock`, `FakeIdGenerator`, `FakeNodeDirectory` and `InMemoryEventPublisher`
from `tests.fakes.knowledge` fit these ports too, so they are not repeated here.
"""

from collections.abc import Iterable, Sequence

from offline_rag.issue.application.errors import IssueNotFoundError, KnowledgeItemNotFoundError
from offline_rag.issue.application.ports import Decomposition, KnowledgePassage
from offline_rag.issue.domain.issue import Issue
from offline_rag.shared_kernel.node_identifier import NodeIdentifier


class InMemoryIssueRepository:
    """Keeps Issues in a dict by id, in the order they were added."""

    def __init__(self, issues: Iterable[Issue] = ()) -> None:
        self.issues: dict[str, Issue] = {issue.issue_id: issue for issue in issues}

    def get_by_id(self, issue_id: str) -> Issue:
        issue = self.issues.get(issue_id)
        if issue is None:
            raise IssueNotFoundError(issue_id)
        return issue

    def find_by_owner(self, node_id: NodeIdentifier) -> list[Issue]:
        return sorted(
            (issue for issue in self.issues.values() if issue.owner_node_id == node_id),
            key=lambda issue: issue.raised_at,
        )

    def add(self, issue: Issue) -> None:
        self.issues[issue.issue_id] = issue

    def save(self, issue: Issue) -> None:
        self.get_by_id(issue.issue_id)
        self.issues[issue.issue_id] = issue


class FakeKnowledgeReader:
    """Returns the passages it was given, by KnowledgeItem id."""

    def __init__(self, passages: Iterable[KnowledgePassage]) -> None:
        self.passages = list(passages)

    def passages_of(self, item_ids: Sequence[str]) -> list[KnowledgePassage]:
        known = {passage.item_id for passage in self.passages}
        for item_id in item_ids:
            if item_id not in known:
                raise KnowledgeItemNotFoundError(item_id)
        return [passage for passage in self.passages if passage.item_id in item_ids]


class FakeIssueDecomposer:
    """Returns a fixed decomposition and remembers what it was asked."""

    def __init__(self, decomposition: Decomposition) -> None:
        self.decomposition = decomposition
        self.calls: list[tuple[str, str, list[KnowledgePassage]]] = []

    def decompose(
        self, *, title: str, description: str, passages: Sequence[KnowledgePassage]
    ) -> Decomposition:
        self.calls.append((title, description, list(passages)))
        return self.decomposition
