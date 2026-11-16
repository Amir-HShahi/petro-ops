"""Use case: say how urgent an Issue is (spec §12.3, §14.2)."""

import structlog

from offline_rag.issue.application.commands import SetIssuePriority
from offline_rag.issue.application.ports import Clock, EventPublisher, IssueRepository
from offline_rag.issue.domain.issue import Issue

log = structlog.get_logger()


class SetIssuePriorityHandler:
    """Sets the priority of an Issue."""

    def __init__(
        self, *, issue_repository: IssueRepository, clock: Clock, event_publisher: EventPublisher
    ) -> None:
        """Create the handler with the ports it needs."""
        self._issue_repository = issue_repository
        self._clock = clock
        self._event_publisher = event_publisher

    def set_priority(self, command: SetIssuePriority) -> Issue:
        """Store the new priority and return the Issue.

        Raises:
            IssueNotFoundError: The Issue does not exist.
            IssueClosedError: The Issue is resolved or archived.
        """
        issue = self._issue_repository.get_by_id(command.issue_id)
        issue.set_priority(command.priority, set_at=self._clock.now())
        self._issue_repository.save(issue)
        self._event_publisher.publish(issue.pull_events())
        log.info(
            "issue_prioritized",
            issue_id=issue.issue_id,
            node_id=issue.owner_node_id.value,
            priority=command.priority.value,
        )
        return issue
