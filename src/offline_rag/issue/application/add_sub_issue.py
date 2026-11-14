"""Use case: split a part off an Issue or off one of its SubIssues by hand (spec §12.2)."""

import structlog

from offline_rag.issue.application.commands import AddSubIssue
from offline_rag.issue.application.ports import (
    Clock,
    EventPublisher,
    IdGenerator,
    IssueRepository,
)
from offline_rag.issue.domain.issue import Issue
from offline_rag.issue.domain.sub_issue import SubIssue

log = structlog.get_logger()


class AddSubIssueHandler:
    """Adds one SubIssue to an Issue's tree, last among its siblings."""

    def __init__(
        self,
        *,
        issue_repository: IssueRepository,
        clock: Clock,
        id_generator: IdGenerator,
        event_publisher: EventPublisher,
    ) -> None:
        """Create the handler with the ports it needs."""
        self._issue_repository = issue_repository
        self._clock = clock
        self._id_generator = id_generator
        self._event_publisher = event_publisher

    def add_sub_issue(self, command: AddSubIssue) -> tuple[Issue, SubIssue]:
        """Store the new SubIssue and return its Issue and the SubIssue.

        Raises:
            IssueNotFoundError: The Issue does not exist.
            SubIssueParentNotFoundError: The parent is not one of the Issue's SubIssues.
            IssueFieldEmptyError: The title or description is empty.
        """
        issue = self._issue_repository.get_by_id(command.issue_id)
        sub_issue = issue.add_sub_issue(
            sub_issue_id=self._id_generator.new_id(),
            parent_id=command.parent_id or issue.issue_id,
            title=command.title,
            description=command.description,
            metadata=command.metadata,
            added_at=self._clock.now(),
        )
        self._issue_repository.save(issue)
        self._event_publisher.publish(issue.pull_events())
        log.info(
            "sub_issue_added",
            issue_id=issue.issue_id,
            sub_issue_id=sub_issue.sub_issue_id,
            node_id=issue.owner_node_id.value,
            position=sub_issue.position,
        )
        return issue, sub_issue
