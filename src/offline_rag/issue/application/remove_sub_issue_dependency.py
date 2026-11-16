"""Use case: stop a SubIssue waiting for another SubIssue of its Issue."""

import structlog

from offline_rag.issue.application.commands import RemoveSubIssueDependency
from offline_rag.issue.application.ports import Clock, EventPublisher, IssueRepository
from offline_rag.issue.domain.issue import Issue

log = structlog.get_logger()


class RemoveSubIssueDependencyHandler:
    """Removes that one SubIssue waits for another."""

    def __init__(
        self, *, issue_repository: IssueRepository, clock: Clock, event_publisher: EventPublisher
    ) -> None:
        """Create the handler with the ports it needs."""
        self._issue_repository = issue_repository
        self._clock = clock
        self._event_publisher = event_publisher

    def remove(self, command: RemoveSubIssueDependency) -> Issue:
        """Store the change and return the Issue.

        Raises:
            IssueNotFoundError: The Issue does not exist.
            SubIssueNotFoundError: The Issue has no such SubIssue.
            SubIssueDependencyNotFoundError: The SubIssue does not wait for the other.
            IssueClosedError: The Issue is resolved or archived.
        """
        issue = self._issue_repository.get_by_id(command.issue_id)
        issue.remove_sub_issue_dependency(
            command.sub_issue_id,
            depends_on_sub_issue_id=command.depends_on_sub_issue_id,
            removed_at=self._clock.now(),
        )
        self._issue_repository.save(issue)
        self._event_publisher.publish(issue.pull_events())
        log.info(
            "sub_issue_dependency_removed",
            issue_id=issue.issue_id,
            node_id=issue.owner_node_id.value,
            sub_issue_id=command.sub_issue_id,
            depends_on_sub_issue_id=command.depends_on_sub_issue_id,
        )
        return issue
