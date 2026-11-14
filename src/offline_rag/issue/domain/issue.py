"""The Issue aggregate root."""

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import replace
from datetime import datetime

from offline_rag.issue.domain.errors import (
    ArchivedIsFinalError,
    InvalidSimilarIssueFlagError,
    InvalidSubIssueCandidateError,
    InvalidSubIssuePositionError,
    IssueClosedError,
    IssueFieldEmptyError,
    IssueHasOpenSubIssuesError,
    ResolveIssueRequiredError,
    SubIssueCandidateAlreadyAcceptedError,
    SubIssueCandidateNotFoundError,
    SubIssueCycleError,
    SubIssueDependencyCycleError,
    SubIssueDependencyNotFoundError,
    SubIssueIdTakenError,
    SubIssueNotFoundError,
    SubIssueParentNotFoundError,
    SubIssuePositionOutOfRangeError,
)
from offline_rag.issue.domain.events import (
    IssueDecomposed,
    IssuePrioritized,
    IssueRaised,
    IssueResolved,
    IssueStatusChanged,
    SimilarIssueFound,
    SubIssueAdded,
    SubIssueDependencyAdded,
    SubIssueDependencyRemoved,
    SubIssueMoved,
)
from offline_rag.issue.domain.issue_priority import IssuePriority
from offline_rag.issue.domain.issue_status import IssueStatus
from offline_rag.issue.domain.similar_issue import SimilarIssueFlag
from offline_rag.issue.domain.sub_issue import SubIssue
from offline_rag.issue.domain.sub_issue_candidate import SubIssueCandidate
from offline_rag.shared_kernel.domain_event import DomainEvent
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier


class Issue:
    """A problem a Node works on, with the tree of SubIssues it is split into (spec §12).

    Invariants:
    - An Issue has an id, a title and a description, and belongs to one Node (spec §12.1).
    - Every SubIssue id is unique within the Issue and differs from the Issue id.
    - A SubIssue's parent is the Issue or another of its SubIssues, and the SubIssues
      form a tree: no SubIssue is its own ancestor (spec §12.2).
    - The SubIssues under one parent are numbered 1, 2, 3 and on, which is their
      place among their siblings (spec §12.2, §12.3).
    - A new Issue keeps what comparing it with the Node's other Issues found, as
      flags (spec §12.1, steps 3 and 4). A flag never points at the Issue itself,
      and each other Issue is flagged at most once.
    - SubIssue candidates the LLM suggested have unique numbers from 1, and an
      accepted candidate names the SubIssue it became (spec §12.2).
    - A SubIssue waits only for other SubIssues of the same Issue, and never, even
      through others, for itself (spec §12.3).
    - Nothing leaves the archived status. An Issue becomes resolved only through
      `resolve`, with a resolution summary, once every SubIssue is closed.
    - A resolved or archived Issue is closed: its SubIssues, candidates and priority
      stay as they are until its status changes again.

    The comparison needs the Node's other Issues, so the application layer runs
    `SimilarIssueDetector` and passes its flags to `raise_issue`.
    """

    def __init__(
        self,
        *,
        issue_id: str,
        owner_node_id: NodeIdentifier,
        title: str,
        description: str,
        metadata: MetadataRecord,
        status: IssueStatus,
        raised_at: datetime,
        sub_issues: Iterable[SubIssue] = (),
        similar_issue_flags: Iterable[SimilarIssueFlag] = (),
        sub_issue_candidates: Iterable[SubIssueCandidate] = (),
        priority: IssuePriority | None = None,
        resolution_summary: str | None = None,
    ) -> None:
        """Rebuild an Issue, for example from storage. Use `raise_issue` for a new one.

        Args:
            issue_id: Stable id of the Issue.
            owner_node_id: The Node the Issue belongs to.
            title: A short name of the Issue.
            description: What the problem is.
            metadata: Its structured metadata (spec §7.5).
            status: Where it stands (spec §14.1).
            raised_at: When the Node defined it, timezone-aware.
            sub_issues: Its SubIssues, in any order.
            similar_issue_flags: The Node's Issues it looked like when it was raised.
            sub_issue_candidates: SubIssues the LLM suggested, accepted or waiting.
            priority: How urgent it is, or None while nobody has said.
            resolution_summary: How it was solved. Required while it is resolved.

        Raises:
            IssueFieldEmptyError: The id, title or description is empty.
            SubIssueIdTakenError: Two SubIssues share an id, or one has the Issue's id.
            SubIssueParentNotFoundError: A SubIssue's parent is not in this Issue.
            SubIssueCycleError: The SubIssues do not form a tree.
            InvalidSubIssuePositionError: The SubIssues under a parent are not numbered
                1, 2, 3 and on.
            InvalidSimilarIssueFlagError: A flag points at the Issue itself, or two
                flags point at the same Issue.
            InvalidSubIssueCandidateError: Two candidates share a number, or an
                accepted one names a SubIssue the Issue does not have.
            SubIssueNotFoundError: A SubIssue waits for one the Issue does not have.
            SubIssueDependencyCycleError: SubIssues wait for each other.
        """
        _require_text(issue_id=issue_id, title=title, description=description)
        self._sub_issues = list(sub_issues)
        _check_sub_issue_tree(issue_id, self._sub_issues)
        self._similar_issue_flags = tuple(similar_issue_flags)
        _check_similar_issue_flags(issue_id, self._similar_issue_flags)
        self._sub_issue_candidates = list(sub_issue_candidates)
        _check_sub_issue_candidates(issue_id, self._sub_issue_candidates, self._sub_issues)
        _check_dependencies(issue_id, self._sub_issues)
        if status == IssueStatus.RESOLVED and not (resolution_summary or "").strip():
            raise IssueFieldEmptyError(field="resolution_summary")
        self._priority = priority
        self._resolution_summary = resolution_summary if status == IssueStatus.RESOLVED else None
        self._issue_id = issue_id
        self._owner_node_id = owner_node_id
        self._title = title
        self._description = description
        self._metadata = metadata
        self._status = status
        self._raised_at = raised_at
        self._pending_events: list[DomainEvent] = []

    @classmethod
    def raise_issue(
        cls,
        *,
        issue_id: str,
        owner_node_id: NodeIdentifier,
        title: str,
        description: str,
        metadata: MetadataRecord,
        raised_at: datetime,
        similar_issue_flags: Iterable[SimilarIssueFlag] = (),
    ) -> "Issue":
        """Define a new Issue for a Node, with no SubIssues yet (spec §12.1).

        The Issue starts as `NEW` and records `IssueRaised`, then one
        `SimilarIssueFound` per flag; take them with `pull_events` after saving.

        Args:
            similar_issue_flags: What `SimilarIssueDetector` found among the Node's
                other Issues.

        Raises:
            IssueFieldEmptyError: The id, title or description is empty.
            InvalidSimilarIssueFlagError: A flag points at the Issue itself, or two
                flags point at the same Issue.
        """
        issue = cls(
            issue_id=issue_id,
            owner_node_id=owner_node_id,
            title=title,
            description=description,
            metadata=metadata,
            status=IssueStatus.NEW,
            raised_at=raised_at,
            similar_issue_flags=similar_issue_flags,
        )
        issue._pending_events.append(
            IssueRaised(occurred_at=raised_at, issue_id=issue_id, owner_node_id=owner_node_id)
        )
        issue._pending_events.extend(
            SimilarIssueFound(
                occurred_at=raised_at,
                issue_id=issue_id,
                similar_issue_id=flag.similar_issue_id,
                kind=flag.kind,
                score=flag.score,
            )
            for flag in issue.similar_issue_flags
        )
        return issue

    @property
    def issue_id(self) -> str:
        """Stable id of the Issue."""
        return self._issue_id

    @property
    def owner_node_id(self) -> NodeIdentifier:
        """The Node the Issue belongs to."""
        return self._owner_node_id

    @property
    def title(self) -> str:
        """A short name of the Issue."""
        return self._title

    @property
    def description(self) -> str:
        """What the problem is."""
        return self._description

    @property
    def metadata(self) -> MetadataRecord:
        """Its structured metadata (spec §7.5)."""
        return self._metadata

    @property
    def status(self) -> IssueStatus:
        """Where it stands (spec §14.1)."""
        return self._status

    @property
    def priority(self) -> IssuePriority | None:
        """How urgent it is, or None while nobody has said (spec §12.3)."""
        return self._priority

    @property
    def resolution_summary(self) -> str | None:
        """How it was solved, while it is resolved."""
        return self._resolution_summary

    @property
    def is_closed(self) -> bool:
        """Whether it is resolved or archived, so its contents may not change."""
        return self._status in (IssueStatus.RESOLVED, IssueStatus.ARCHIVED)

    @property
    def raised_at(self) -> datetime:
        """When the Node defined the Issue."""
        return self._raised_at

    @property
    def similar_issue_flags(self) -> tuple[SimilarIssueFlag, ...]:
        """The Node's Issues this one looked like when it was raised, strongest first."""
        return self._similar_issue_flags

    @property
    def sub_issue_candidates(self) -> tuple[SubIssueCandidate, ...]:
        """SubIssues the LLM suggested, accepted or waiting, by number."""
        return tuple(sorted(self._sub_issue_candidates, key=lambda candidate: candidate.number))

    @property
    def sub_issues(self) -> tuple[SubIssue, ...]:
        """Every SubIssue in the tree, at any depth."""
        return tuple(self._sub_issues)

    def children_of(self, parent_id: str) -> tuple[SubIssue, ...]:
        """Return the SubIssues directly under `parent_id`, in their order among siblings.

        Args:
            parent_id: The Issue id for the top SubIssues, or a SubIssue id.
        """
        return tuple(
            sorted(
                (sub for sub in self._sub_issues if sub.parent_id == parent_id),
                key=lambda sub: sub.position,
            )
        )

    def add_sub_issue(
        self,
        *,
        sub_issue_id: str,
        parent_id: str,
        title: str,
        description: str,
        metadata: MetadataRecord,
        added_at: datetime,
    ) -> SubIssue:
        """Split a part off this Issue or off one of its SubIssues (spec §12.2).

        The new SubIssue starts as `NEW` and goes last among the children of its parent.
        The Issue records `SubIssueAdded`; take it with `pull_events` after saving.

        Args:
            parent_id: The Issue id, or the id of the SubIssue being split.
            added_at: When it was added, timezone-aware.

        Raises:
            IssueFieldEmptyError: The id, title or description is empty.
            SubIssueIdTakenError: The id is the Issue's or another SubIssue's.
            SubIssueParentNotFoundError: The parent is not this Issue or one of its
                SubIssues.
            IssueClosedError: The Issue is resolved or archived.
        """
        self._require_open()
        sub_issue = self._append_sub_issue(
            sub_issue_id=sub_issue_id,
            parent_id=parent_id,
            title=title,
            description=description,
            metadata=metadata,
        )
        self._pending_events.append(
            SubIssueAdded(
                occurred_at=added_at,
                issue_id=self._issue_id,
                sub_issue_id=sub_issue_id,
                parent_id=parent_id,
                position=sub_issue.position,
            )
        )
        return sub_issue

    def propose_sub_issue_candidates(
        self, candidates: Sequence[SubIssueCandidate]
    ) -> tuple[SubIssueCandidate, ...]:
        """Replace the waiting candidates with new LLM suggestions (spec §12.2).

        Accepted candidates stay, as the record of what each SubIssue came from. The
        new ones keep their given order and are numbered after every earlier
        candidate, so an old number never names a new suggestion.

        Args:
            candidates: The suggestions, in the order the LLM gave them. Their own
                numbers are replaced.

        Returns:
            The new candidates with their numbers.

        Raises:
            IssueClosedError: The Issue is resolved or archived.
        """
        self._require_open()
        next_number = max((candidate.number for candidate in self._sub_issue_candidates), default=0)
        numbered = tuple(
            replace(candidate, number=next_number + offset, accepted_sub_issue_id=None)
            for offset, candidate in enumerate(candidates, start=1)
        )
        self._sub_issue_candidates = [
            candidate for candidate in self._sub_issue_candidates if candidate.is_accepted
        ] + list(numbered)
        return numbered

    def accept_sub_issue_candidates(
        self,
        *,
        numbers: Sequence[int],
        sub_issue_ids: Sequence[str],
        accepted_at: datetime,
    ) -> tuple[SubIssue, ...]:
        """Turn chosen candidates into SubIssues of this Issue, in the order given.

        Each becomes a SubIssue right under the Issue, last among its siblings. The
        Issue records one `IssueDecomposed`. Nothing changes when a number is wrong.

        Args:
            numbers: The candidates to accept. A number given twice counts once.
            sub_issue_ids: A new id for each distinct number, in the same order.
            accepted_at: When they were accepted, timezone-aware.

        Raises:
            SubIssueCandidateNotFoundError: The Issue has no candidate with a number.
            SubIssueCandidateAlreadyAcceptedError: A candidate is a SubIssue already.
            SubIssueIdTakenError: A new id is already used in the Issue.
            IssueClosedError: The Issue is resolved or archived.
        """
        self._require_open()
        chosen = [self._waiting_candidate(number) for number in dict.fromkeys(numbers)]
        accepted: list[SubIssue] = []
        for candidate, sub_issue_id in zip(chosen, sub_issue_ids, strict=True):
            accepted.append(
                self._append_sub_issue(
                    sub_issue_id=sub_issue_id,
                    parent_id=self._issue_id,
                    title=candidate.title,
                    description=candidate.description,
                    metadata=MetadataRecord(),
                )
            )
            self._sub_issue_candidates = [
                replace(other, accepted_sub_issue_id=sub_issue_id)
                if other.number == candidate.number
                else other
                for other in self._sub_issue_candidates
            ]
        self._pending_events.append(
            IssueDecomposed(
                occurred_at=accepted_at,
                issue_id=self._issue_id,
                sub_issue_ids=tuple(sub.sub_issue_id for sub in accepted),
            )
        )
        return tuple(accepted)

    def set_priority(self, priority: IssuePriority, *, set_at: datetime) -> None:
        """Say how urgent the Issue is (spec §12.3, §14.2).

        The Issue records `IssuePrioritized` when the priority changes.

        Raises:
            IssueClosedError: The Issue is resolved or archived.
        """
        self._require_open()
        if priority == self._priority:
            return
        self._priority = priority
        self._pending_events.append(
            IssuePrioritized(occurred_at=set_at, issue_id=self._issue_id, priority=priority)
        )

    def move_sub_issue(self, sub_issue_id: str, *, position: int, moved_at: datetime) -> None:
        """Move a SubIssue to another place among its siblings (spec §12.2, §12.3).

        The siblings between its old and new place move along by one. The Issue
        records `SubIssueMoved` when the place changes.

        Args:
            position: The new place, from 1 to the number of siblings.

        Raises:
            SubIssueNotFoundError: The Issue has no such SubIssue.
            SubIssuePositionOutOfRangeError: The siblings have no such place.
            IssueClosedError: The Issue is resolved or archived.
        """
        self._require_open()
        moving = self._get_sub_issue(sub_issue_id)
        siblings = [sub for sub in self.children_of(moving.parent_id) if sub != moving]
        if not 1 <= position <= len(siblings) + 1:
            raise SubIssuePositionOutOfRangeError(
                sub_issue_id=sub_issue_id, position=position, sibling_count=len(siblings) + 1
            )
        if position == moving.position:
            return
        siblings.insert(position - 1, moving)
        new_position = {sub.sub_issue_id: place for place, sub in enumerate(siblings, start=1)}
        self._sub_issues = [
            sub.with_changes(position=new_position[sub.sub_issue_id])
            if sub.sub_issue_id in new_position
            else sub
            for sub in self._sub_issues
        ]
        self._pending_events.append(
            SubIssueMoved(
                occurred_at=moved_at,
                issue_id=self._issue_id,
                sub_issue_id=sub_issue_id,
                position=position,
            )
        )

    def add_sub_issue_dependency(
        self, sub_issue_id: str, *, depends_on_sub_issue_id: str, added_at: datetime
    ) -> None:
        """Make a SubIssue wait for another SubIssue of this Issue (spec §12.3).

        The Issue records `SubIssueDependencyAdded`; adding one that exists changes
        nothing.

        Raises:
            SubIssueNotFoundError: The Issue has no such SubIssue.
            SubIssueDependencyCycleError: The two would, even through others, wait
                for each other.
            IssueClosedError: The Issue is resolved or archived.
        """
        self._require_open()
        waiting = self._get_sub_issue(sub_issue_id)
        self._get_sub_issue(depends_on_sub_issue_id)
        if depends_on_sub_issue_id in waiting.depends_on:
            return
        cycle = _dependency_path(self._sub_issues, depends_on_sub_issue_id, sub_issue_id)
        if cycle is not None:
            raise SubIssueDependencyCycleError(
                issue_id=self._issue_id, sub_issue_ids=sorted({sub_issue_id, *cycle})
            )
        self._replace_sub_issue(
            waiting.with_changes(depends_on=(*waiting.depends_on, depends_on_sub_issue_id))
        )
        self._pending_events.append(
            SubIssueDependencyAdded(
                occurred_at=added_at,
                issue_id=self._issue_id,
                sub_issue_id=sub_issue_id,
                depends_on_sub_issue_id=depends_on_sub_issue_id,
            )
        )

    def remove_sub_issue_dependency(
        self, sub_issue_id: str, *, depends_on_sub_issue_id: str, removed_at: datetime
    ) -> None:
        """Stop a SubIssue waiting for another SubIssue of this Issue.

        The Issue records `SubIssueDependencyRemoved`.

        Raises:
            SubIssueNotFoundError: The Issue has no such SubIssue.
            SubIssueDependencyNotFoundError: The SubIssue does not wait for the other.
            IssueClosedError: The Issue is resolved or archived.
        """
        self._require_open()
        waiting = self._get_sub_issue(sub_issue_id)
        if depends_on_sub_issue_id not in waiting.depends_on:
            raise SubIssueDependencyNotFoundError(
                sub_issue_id=sub_issue_id, depends_on_sub_issue_id=depends_on_sub_issue_id
            )
        self._replace_sub_issue(
            waiting.with_changes(
                depends_on=tuple(
                    other for other in waiting.depends_on if other != depends_on_sub_issue_id
                )
            )
        )
        self._pending_events.append(
            SubIssueDependencyRemoved(
                occurred_at=removed_at,
                issue_id=self._issue_id,
                sub_issue_id=sub_issue_id,
                depends_on_sub_issue_id=depends_on_sub_issue_id,
            )
        )

    def change_status(
        self, status: IssueStatus, *, changed_at: datetime, sub_issue_id: str | None = None
    ) -> None:
        """Move the Issue, or one of its SubIssues, to another status (spec §14.1).

        Any status may follow any other, except that nothing leaves archived and the
        Issue itself becomes resolved only through `resolve`. Moving a resolved Issue
        to another status reopens it and drops its resolution summary. The Issue
        records `IssueStatusChanged` when the status changes.

        Args:
            sub_issue_id: The SubIssue to change, or None for the Issue itself.

        Raises:
            ArchivedIsFinalError: The Issue or SubIssue is archived.
            ResolveIssueRequiredError: The Issue itself was set to resolved.
            SubIssueNotFoundError: The Issue has no such SubIssue.
            IssueClosedError: A SubIssue was changed while the Issue is closed.
        """
        if sub_issue_id is None:
            previous = self._status
            if previous == status:
                return
            if previous == IssueStatus.ARCHIVED:
                raise ArchivedIsFinalError(issue_id=self._issue_id, sub_issue_id=None)
            if status == IssueStatus.RESOLVED:
                raise ResolveIssueRequiredError(self._issue_id)
            self._status = status
            self._resolution_summary = None
        else:
            self._require_open()
            sub_issue = self._get_sub_issue(sub_issue_id)
            previous = sub_issue.status
            if previous == status:
                return
            if previous == IssueStatus.ARCHIVED:
                raise ArchivedIsFinalError(issue_id=self._issue_id, sub_issue_id=sub_issue_id)
            self._replace_sub_issue(sub_issue.with_changes(status=status))
        self._pending_events.append(
            IssueStatusChanged(
                occurred_at=changed_at,
                issue_id=self._issue_id,
                sub_issue_id=sub_issue_id,
                previous_status=previous,
                status=status,
            )
        )

    def resolve(self, resolution_summary: str, *, resolved_at: datetime) -> None:
        """Mark the Issue resolved, with how it was solved.

        Every SubIssue must be closed first. The Issue records `IssueStatusChanged`
        and `IssueResolved`, which hands the resolution to Knowledge Management.

        Raises:
            IssueFieldEmptyError: The resolution summary is empty.
            IssueClosedError: The Issue is already resolved or archived.
            IssueHasOpenSubIssuesError: Some SubIssues are not closed yet.
        """
        if not resolution_summary.strip():
            raise IssueFieldEmptyError(field="resolution_summary")
        self._require_open()
        open_ids = [sub.sub_issue_id for sub in self._sub_issues if not sub.is_closed]
        if open_ids:
            raise IssueHasOpenSubIssuesError(issue_id=self._issue_id, sub_issue_ids=open_ids)
        previous = self._status
        self._status = IssueStatus.RESOLVED
        self._resolution_summary = resolution_summary
        self._pending_events.append(
            IssueStatusChanged(
                occurred_at=resolved_at,
                issue_id=self._issue_id,
                sub_issue_id=None,
                previous_status=previous,
                status=IssueStatus.RESOLVED,
            )
        )
        self._pending_events.append(
            IssueResolved(
                occurred_at=resolved_at,
                issue_id=self._issue_id,
                owner_node_id=self._owner_node_id,
                resolution_summary=resolution_summary,
            )
        )

    def _require_open(self) -> None:
        if self.is_closed:
            raise IssueClosedError(issue_id=self._issue_id, status=self._status.value)

    def _get_sub_issue(self, sub_issue_id: str) -> SubIssue:
        found = next((sub for sub in self._sub_issues if sub.sub_issue_id == sub_issue_id), None)
        if found is None:
            raise SubIssueNotFoundError(issue_id=self._issue_id, sub_issue_id=sub_issue_id)
        return found

    def _replace_sub_issue(self, changed: SubIssue) -> None:
        self._sub_issues = [changed if sub == changed else sub for sub in self._sub_issues]

    def _waiting_candidate(self, number: int) -> SubIssueCandidate:
        candidate = next(
            (other for other in self._sub_issue_candidates if other.number == number), None
        )
        if candidate is None:
            raise SubIssueCandidateNotFoundError(issue_id=self._issue_id, number=number)
        if candidate.accepted_sub_issue_id is not None:
            raise SubIssueCandidateAlreadyAcceptedError(
                issue_id=self._issue_id,
                number=number,
                sub_issue_id=candidate.accepted_sub_issue_id,
            )
        return candidate

    def _append_sub_issue(
        self,
        *,
        sub_issue_id: str,
        parent_id: str,
        title: str,
        description: str,
        metadata: MetadataRecord,
    ) -> SubIssue:
        if sub_issue_id == self._issue_id or any(
            sub.sub_issue_id == sub_issue_id for sub in self._sub_issues
        ):
            raise SubIssueIdTakenError(issue_id=self._issue_id, sub_issue_id=sub_issue_id)
        if parent_id != self._issue_id and all(
            sub.sub_issue_id != parent_id for sub in self._sub_issues
        ):
            raise SubIssueParentNotFoundError(
                issue_id=self._issue_id, sub_issue_id=sub_issue_id, parent_id=parent_id
            )
        sub_issue = SubIssue(
            sub_issue_id=sub_issue_id,
            parent_id=parent_id,
            position=len(self.children_of(parent_id)) + 1,
            title=title,
            description=description,
            metadata=metadata,
            status=IssueStatus.NEW,
        )
        self._sub_issues.append(sub_issue)
        return sub_issue

    def pull_events(self) -> tuple[DomainEvent, ...]:
        """Return the events recorded since the last call, and forget them."""
        events = tuple(self._pending_events)
        self._pending_events.clear()
        return events

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Issue) and other.issue_id == self._issue_id

    def __hash__(self) -> int:
        return hash(self._issue_id)


def _require_text(**values: str) -> None:
    for field, value in values.items():
        if not value.strip():
            raise IssueFieldEmptyError(field=field)


def _check_similar_issue_flags(issue_id: str, flags: tuple[SimilarIssueFlag, ...]) -> None:
    seen: set[str] = set()
    for flag in flags:
        if flag.similar_issue_id == issue_id or flag.similar_issue_id in seen:
            raise InvalidSimilarIssueFlagError(
                issue_id=issue_id, similar_issue_id=flag.similar_issue_id
            )
        seen.add(flag.similar_issue_id)


def _check_sub_issue_candidates(
    issue_id: str, candidates: list[SubIssueCandidate], sub_issues: list[SubIssue]
) -> None:
    sub_issue_ids = {sub.sub_issue_id for sub in sub_issues}
    number_counts = Counter(candidate.number for candidate in candidates)
    for candidate in candidates:
        is_lost = (
            candidate.accepted_sub_issue_id is not None
            and candidate.accepted_sub_issue_id not in sub_issue_ids
        )
        if candidate.number < 1 or number_counts[candidate.number] > 1 or is_lost:
            raise InvalidSubIssueCandidateError(issue_id=issue_id, number=candidate.number)


def _check_dependencies(issue_id: str, sub_issues: list[SubIssue]) -> None:
    known = {sub.sub_issue_id for sub in sub_issues}
    for sub in sub_issues:
        for other in sub.depends_on:
            if other not in known:
                raise SubIssueNotFoundError(issue_id=issue_id, sub_issue_id=other)
            cycle = _dependency_path(sub_issues, other, sub.sub_issue_id)
            if cycle is not None:
                raise SubIssueDependencyCycleError(
                    issue_id=issue_id, sub_issue_ids=sorted({sub.sub_issue_id, *cycle})
                )


def _dependency_path(sub_issues: list[SubIssue], start: str, target: str) -> list[str] | None:
    """Return the SubIssues from `start` that lead, by waiting, to `target`, or None."""
    depends_on = {sub.sub_issue_id: sub.depends_on for sub in sub_issues}
    stack: list[tuple[str, list[str]]] = [(start, [start])]
    seen: set[str] = set()
    while stack:
        current, path = stack.pop()
        if current == target:
            return path
        if current in seen:
            continue
        seen.add(current)
        stack.extend((other, [*path, other]) for other in depends_on.get(current, ()))
    return None


def _check_sub_issue_tree(issue_id: str, sub_issues: list[SubIssue]) -> None:
    id_counts = Counter(sub.sub_issue_id for sub in sub_issues)
    for sub in sub_issues:
        if sub.sub_issue_id == issue_id or id_counts[sub.sub_issue_id] > 1:
            raise SubIssueIdTakenError(issue_id=issue_id, sub_issue_id=sub.sub_issue_id)

    parent_by_id = {sub.sub_issue_id: sub.parent_id for sub in sub_issues}
    for sub in sub_issues:
        if sub.parent_id != issue_id and sub.parent_id not in parent_by_id:
            raise SubIssueParentNotFoundError(
                issue_id=issue_id, sub_issue_id=sub.sub_issue_id, parent_id=sub.parent_id
            )
    _check_no_cycle(issue_id, parent_by_id)

    positions_by_parent: dict[str, list[int]] = {}
    for sub in sub_issues:
        positions_by_parent.setdefault(sub.parent_id, []).append(sub.position)
    for parent_id, positions in positions_by_parent.items():
        if sorted(positions) != list(range(1, len(positions) + 1)):
            raise InvalidSubIssuePositionError(
                issue_id=issue_id, parent_id=parent_id, positions=sorted(positions)
            )


def _check_no_cycle(issue_id: str, parent_by_id: dict[str, str]) -> None:
    for start in parent_by_id:
        path: list[str] = []
        current = start
        while current != issue_id:
            if current in path:
                cycle = path[path.index(current) :]
                raise SubIssueCycleError(issue_id=issue_id, sub_issue_ids=sorted(cycle))
            path.append(current)
            current = parent_by_id[current]
