"""In-memory fakes of the Issue Management ports, for unit tests.

`FakeClock`, `FakeIdGenerator`, `FakeNodeDirectory` and `InMemoryEventPublisher`
from `tests.fakes.knowledge` fit these ports too, so they are not repeated here.
"""

from collections.abc import Iterable

from offline_rag.issue.application.errors import IssueNotFoundError
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
