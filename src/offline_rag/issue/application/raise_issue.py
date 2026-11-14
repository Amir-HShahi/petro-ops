"""Use case: define a new Issue for a Node (spec §12.1)."""

import structlog

from offline_rag.issue.application.commands import RaiseIssue
from offline_rag.issue.application.errors import OwnerNodeNotFoundError
from offline_rag.issue.application.ports import (
    Clock,
    EventPublisher,
    IdGenerator,
    IssueRepository,
    NodeDirectory,
)
from offline_rag.issue.domain.issue import Issue

log = structlog.get_logger()


class RaiseIssueHandler:
    """Records a new Issue for a registered Node.

    Comparing it with the Node's other Issues (spec §12.1, steps 3 and 4) is added
    with the similar-Issue check.
    """

    def __init__(
        self,
        *,
        issue_repository: IssueRepository,
        node_directory: NodeDirectory,
        clock: Clock,
        id_generator: IdGenerator,
        event_publisher: EventPublisher,
    ) -> None:
        """Create the handler with the ports it needs."""
        self._issue_repository = issue_repository
        self._node_directory = node_directory
        self._clock = clock
        self._id_generator = id_generator
        self._event_publisher = event_publisher

    def raise_issue(self, command: RaiseIssue) -> Issue:
        """Store the new Issue and return it.

        Raises:
            OwnerNodeNotFoundError: The owner Node is not registered.
            IssueFieldEmptyError: The title or description is empty.
        """
        if not self._node_directory.has_node(command.owner_node_id):
            raise OwnerNodeNotFoundError(command.owner_node_id)
        issue = Issue.raise_issue(
            issue_id=self._id_generator.new_id(),
            owner_node_id=command.owner_node_id,
            title=command.title,
            description=command.description,
            metadata=command.metadata,
            raised_at=self._clock.now(),
        )
        self._issue_repository.add(issue)
        self._event_publisher.publish(issue.pull_events())
        log.info("issue_raised", issue_id=issue.issue_id, node_id=issue.owner_node_id.value)
        return issue
