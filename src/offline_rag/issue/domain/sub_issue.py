"""A SubIssue: a smaller Issue inside an Issue's tree (spec §12.2)."""

from offline_rag.issue.domain.errors import IssueFieldEmptyError
from offline_rag.issue.domain.issue_status import CLOSED_STATUSES, IssueStatus
from offline_rag.shared_kernel.metadata_record import MetadataRecord


class SubIssue:
    """A part of an Issue with its own id, status and place among its siblings (spec §12.2).

    A SubIssue lives inside its Issue's aggregate. Its parent is the Issue itself or
    another SubIssue of the same Issue, so SubIssues form a tree. It may also wait for
    other SubIssues of the same Issue (spec §12.3). The Issue checks the tree and the
    dependencies; a SubIssue alone only checks its own fields.
    """

    def __init__(
        self,
        *,
        sub_issue_id: str,
        parent_id: str,
        position: int,
        title: str,
        description: str,
        metadata: MetadataRecord,
        status: IssueStatus,
        depends_on: tuple[str, ...] = (),
    ) -> None:
        """Rebuild a SubIssue. A new one is added with `Issue.add_sub_issue`.

        Args:
            sub_issue_id: Its own id, unique within the Issue.
            parent_id: The id of its Issue, or of the SubIssue it was split from.
            position: Its place among the SubIssues of the same parent, from 1.
            title: A short name of the SubIssue.
            description: What the SubIssue is about.
            metadata: Its structured metadata (spec §7.5).
            status: Where it stands (spec §14.1).
            depends_on: The SubIssues of the same Issue it waits for.

        Raises:
            IssueFieldEmptyError: The id, parent id, title or description is empty.
        """
        _require_text(
            sub_issue_id=sub_issue_id, parent_id=parent_id, title=title, description=description
        )
        self._sub_issue_id = sub_issue_id
        self._parent_id = parent_id
        self._position = position
        self._title = title
        self._description = description
        self._metadata = metadata
        self._status = status
        self._depends_on = tuple(dict.fromkeys(depends_on))

    @property
    def sub_issue_id(self) -> str:
        """Its own id, unique within the Issue."""
        return self._sub_issue_id

    @property
    def parent_id(self) -> str:
        """The id of its Issue, or of the SubIssue it was split from."""
        return self._parent_id

    @property
    def position(self) -> int:
        """Its place among the SubIssues of the same parent, from 1."""
        return self._position

    @property
    def title(self) -> str:
        """A short name of the SubIssue."""
        return self._title

    @property
    def description(self) -> str:
        """What the SubIssue is about."""
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
    def depends_on(self) -> tuple[str, ...]:
        """The SubIssues of the same Issue it waits for (spec §12.3)."""
        return self._depends_on

    @property
    def is_closed(self) -> bool:
        """Whether its work is over: resolved, unresolved or archived."""
        return self._status in CLOSED_STATUSES

    def with_changes(
        self,
        *,
        position: int | None = None,
        status: IssueStatus | None = None,
        depends_on: tuple[str, ...] | None = None,
    ) -> "SubIssue":
        """Return a copy with a new position, status or dependencies; the rest is kept."""
        return SubIssue(
            sub_issue_id=self._sub_issue_id,
            parent_id=self._parent_id,
            position=self._position if position is None else position,
            title=self._title,
            description=self._description,
            metadata=self._metadata,
            status=self._status if status is None else status,
            depends_on=self._depends_on if depends_on is None else depends_on,
        )

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SubIssue) and other.sub_issue_id == self._sub_issue_id

    def __hash__(self) -> int:
        return hash(self._sub_issue_id)


def _require_text(**values: str) -> None:
    for field, value in values.items():
        if not value.strip():
            raise IssueFieldEmptyError(field=field)
