"""Use case: mark an Issue resolved, with how it was solved (spec §14.1)."""

import structlog

from offline_rag.issue.application.commands import ResolveIssue
from offline_rag.issue.application.ports import Clock, EventPublisher, IssueRepository
from offline_rag.issue.domain.issue import Issue

log = structlog.get_logger()


class ResolveIssueHandler:
    """Resolves an Issue once all its SubIssues are closed.

    `IssueResolved` carries the resolution, so Knowledge Management can keep it as
    knowledge (docs/application-services.md, `StoreResolutionAsKnowledge`).
    """

    def __init__(
        self, *, issue_repository: IssueRepository, clock: Clock, event_publisher: EventPublisher
    ) -> None:
        """Create the handler with the ports it needs."""
        self._issue_repository = issue_repository
        self._clock = clock
        self._event_publisher = event_publisher

    def resolve(self, command: ResolveIssue) -> Issue:
        """Store the resolved Issue and return it.

        Raises:
            IssueNotFoundError: The Issue does not exist.
            IssueFieldEmptyError: The resolution summary is empty.
            IssueClosedError: The Issue is already resolved or archived.
            IssueHasOpenSubIssuesError: Some SubIssues are not closed yet.
        """
        issue = self._issue_repository.get_by_id(command.issue_id)
        issue.resolve(command.resolution_summary, resolved_at=self._clock.now())
        self._issue_repository.save(issue)
        self._event_publisher.publish(issue.pull_events())
        log.info(
            "issue_resolved",
            issue_id=issue.issue_id,
            node_id=issue.owner_node_id.value,
            sub_issues=len(issue.sub_issues),
        )
        return issue
