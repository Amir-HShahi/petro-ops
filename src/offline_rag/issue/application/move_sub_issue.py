"""Use case: move a SubIssue to another place among its siblings (spec §12.3)."""

import structlog

from offline_rag.issue.application.commands import MoveSubIssue
from offline_rag.issue.application.ports import Clock, EventPublisher, IssueRepository
from offline_rag.issue.domain.issue import Issue

log = structlog.get_logger()


class MoveSubIssueHandler:
    """Changes the order of a SubIssue among its siblings."""

    def __init__(
        self, *, issue_repository: IssueRepository, clock: Clock, event_publisher: EventPublisher
    ) -> None:
        """Create the handler with the ports it needs."""
        self._issue_repository = issue_repository
        self._clock = clock
        self._event_publisher = event_publisher

    def move(self, command: MoveSubIssue) -> Issue:
        """Store the new order and return the Issue.

        Raises:
            IssueNotFoundError: The Issue does not exist.
            SubIssueNotFoundError: The Issue has no such SubIssue.
            SubIssuePositionOutOfRangeError: The siblings have no such place.
            IssueClosedError: The Issue is resolved or archived.
        """
        issue = self._issue_repository.get_by_id(command.issue_id)
        issue.move_sub_issue(
            command.sub_issue_id, position=command.position, moved_at=self._clock.now()
        )
        self._issue_repository.save(issue)
        self._event_publisher.publish(issue.pull_events())
        log.info(
            "sub_issue_moved",
            issue_id=issue.issue_id,
            node_id=issue.owner_node_id.value,
            sub_issue_id=command.sub_issue_id,
            position=command.position,
        )
        return issue
