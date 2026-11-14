"""Read-only queries on Issues, shared by the CLI and later the API."""

from offline_rag.issue.application.ports import IssueRepository
from offline_rag.issue.domain.issue import Issue
from offline_rag.shared_kernel.node_identifier import NodeIdentifier


class IssueQueries:
    """Reads Issues with their SubIssues."""

    def __init__(self, *, issue_repository: IssueRepository) -> None:
        """Create the queries over the Issue store."""
        self._issue_repository = issue_repository

    def get(self, issue_id: str) -> Issue:
        """Return the Issue with this id, with all its SubIssues.

        Raises:
            IssueNotFoundError: No Issue has this id.
        """
        return self._issue_repository.get_by_id(issue_id)

    def list_by_owner(self, node_id: NodeIdentifier) -> list[Issue]:
        """Return every Issue of this Node, oldest first."""
        return self._issue_repository.find_by_owner(node_id)
