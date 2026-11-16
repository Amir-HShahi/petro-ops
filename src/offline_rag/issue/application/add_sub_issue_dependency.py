"""Use case: make a SubIssue wait for another SubIssue of its Issue (spec §12.3)."""

import structlog

from offline_rag.issue.application.commands import AddSubIssueDependency
from offline_rag.issue.application.ports import Clock, EventPublisher, IssueRepository
from offline_rag.issue.domain.issue import Issue

log = structlog.get_logger()


class AddSubIssueDependencyHandler:
    """Records that one SubIssue waits for another."""

    def __init__(
        self, *, issue_repository: IssueRepository, clock: Clock, event_publisher: EventPublisher
    ) -> None:
        """Create the handler with the ports it needs."""
        self._issue_repository = issue_repository
        self._clock = clock
        self._event_publisher = event_publisher

    def add(self, command: AddSubIssueDependency) -> Issue:
        """Store the dependency and return the Issue.

        Raises:
            IssueNotFoundError: The Issue does not exist.
            SubIssueNotFoundError: The Issue has no such SubIssue.
            SubIssueDependencyCycleError: The SubIssues would wait for each other.
            IssueClosedError: The Issue is resolved or archived.
        """
        issue = self._issue_repository.get_by_id(command.issue_id)
        issue.add_sub_issue_dependency(
            command.sub_issue_id,
            depends_on_sub_issue_id=command.depends_on_sub_issue_id,
            added_at=self._clock.now(),
        )
        self._issue_repository.save(issue)
        self._event_publisher.publish(issue.pull_events())
        log.info(
            "sub_issue_dependency_added",
            issue_id=issue.issue_id,
            node_id=issue.owner_node_id.value,
            sub_issue_id=command.sub_issue_id,
            depends_on_sub_issue_id=command.depends_on_sub_issue_id,
        )
        return issue
