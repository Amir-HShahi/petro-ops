"""Use case: accept SubIssue candidates the LLM suggested (spec §12.2)."""

import structlog

from offline_rag.issue.application.commands import AcceptSubIssueCandidates
from offline_rag.issue.application.ports import (
    Clock,
    EventPublisher,
    IdGenerator,
    IssueRepository,
)
from offline_rag.issue.domain.issue import Issue

log = structlog.get_logger()


class AcceptSubIssueCandidatesHandler:
    """Turns the candidates a person chose into SubIssues of the Issue."""

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

    def accept(self, command: AcceptSubIssueCandidates) -> Issue:
        """Store the new SubIssues and return the Issue.

        Raises:
            IssueNotFoundError: The Issue does not exist.
            SubIssueCandidateNotFoundError: The Issue has no candidate with a number.
            SubIssueCandidateAlreadyAcceptedError: A candidate is a SubIssue already.
        """
        issue = self._issue_repository.get_by_id(command.issue_id)
        numbers = tuple(dict.fromkeys(command.numbers))
        accepted = issue.accept_sub_issue_candidates(
            numbers=numbers,
            sub_issue_ids=[self._id_generator.new_id() for _ in numbers],
            accepted_at=self._clock.now(),
        )
        self._issue_repository.save(issue)
        self._event_publisher.publish(issue.pull_events())
        log.info(
            "sub_issue_candidates_accepted",
            issue_id=issue.issue_id,
            node_id=issue.owner_node_id.value,
            sub_issues=len(accepted),
        )
        return issue
