"""The Issue aggregate root."""

from collections import Counter
from collections.abc import Iterable
from datetime import datetime

from offline_rag.issue.domain.errors import (
    InvalidSubIssuePositionError,
    IssueFieldEmptyError,
    SubIssueCycleError,
    SubIssueIdTakenError,
    SubIssueParentNotFoundError,
)
from offline_rag.issue.domain.events import IssueRaised
from offline_rag.issue.domain.issue_status import IssueStatus
from offline_rag.issue.domain.sub_issue import SubIssue
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

    Comparing a new Issue with the Node's other Issues needs those Issues, so the
    application layer does it before `raise_issue` (spec §12.1).
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

        Raises:
            IssueFieldEmptyError: The id, title or description is empty.
            SubIssueIdTakenError: Two SubIssues share an id, or one has the Issue's id.
            SubIssueParentNotFoundError: A SubIssue's parent is not in this Issue.
            SubIssueCycleError: The SubIssues do not form a tree.
            InvalidSubIssuePositionError: The SubIssues under a parent are not numbered
                1, 2, 3 and on.
        """
        _require_text(issue_id=issue_id, title=title, description=description)
        self._sub_issues = list(sub_issues)
        _check_sub_issue_tree(issue_id, self._sub_issues)
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
    ) -> "Issue":
        """Define a new Issue for a Node, with no SubIssues yet (spec §12.1).

        The Issue starts as `NEW` and records `IssueRaised`; take it with `pull_events`
        after saving.

        Raises:
            IssueFieldEmptyError: The id, title or description is empty.
        """
        issue = cls(
            issue_id=issue_id,
            owner_node_id=owner_node_id,
            title=title,
            description=description,
            metadata=metadata,
            status=IssueStatus.NEW,
            raised_at=raised_at,
        )
        issue._pending_events.append(
            IssueRaised(occurred_at=raised_at, issue_id=issue_id, owner_node_id=owner_node_id)
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
    def raised_at(self) -> datetime:
        """When the Node defined the Issue."""
        return self._raised_at

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
    ) -> SubIssue:
        """Split a part off this Issue or off one of its SubIssues (spec §12.2).

        The new SubIssue starts as `NEW` and goes last among the children of its parent.

        Args:
            parent_id: The Issue id, or the id of the SubIssue being split.

        Raises:
            IssueFieldEmptyError: The id, title or description is empty.
            SubIssueIdTakenError: The id is the Issue's or another SubIssue's.
            SubIssueParentNotFoundError: The parent is not this Issue or one of its
                SubIssues.
        """
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
