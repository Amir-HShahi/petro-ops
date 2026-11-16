"""Use case: move an Issue or one of its SubIssues to another status (spec §14.1)."""

import structlog

from offline_rag.issue.application.commands import ChangeIssueStatus
from offline_rag.issue.application.ports import Clock, EventPublisher, IssueRepository
from offline_rag.issue.domain.issue import Issue

log = structlog.get_logger()


class ChangeIssueStatusHandler:
    """Changes the status of an Issue or one of its SubIssues."""

    def __init__(
        self, *, issue_repository: IssueRepository, clock: Clock, event_publisher: EventPublisher
    ) -> None:
        """Create the handler with the ports it needs."""
        self._issue_repository = issue_repository
        self._clock = clock
        self._event_publisher = event_publisher

    def change(self, command: ChangeIssueStatus) -> Issue:
        """Store the new status and return the Issue.

        Raises:
            IssueNotFoundError: The Issue does not exist.
            ArchivedIsFinalError: The Issue or SubIssue is archived.
            ResolveIssueRequiredError: The Issue itself was set to resolved.
            SubIssueNotFoundError: The Issue has no such SubIssue.
            IssueClosedError: A SubIssue was changed while the Issue is closed.
        """
        issue = self._issue_repository.get_by_id(command.issue_id)
        issue.change_status(
            command.status, changed_at=self._clock.now(), sub_issue_id=command.sub_issue_id
        )
        self._issue_repository.save(issue)
        self._event_publisher.publish(issue.pull_events())
        log.info(
            "issue_status_changed",
            issue_id=issue.issue_id,
            node_id=issue.owner_node_id.value,
            sub_issue_id=command.sub_issue_id,
            status=command.status.value,
        )
        return issue
