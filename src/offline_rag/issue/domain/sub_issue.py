"""A SubIssue: a smaller Issue inside an Issue's tree (spec §12.2)."""

from offline_rag.issue.domain.errors import IssueFieldEmptyError
from offline_rag.issue.domain.issue_status import IssueStatus
from offline_rag.shared_kernel.metadata_record import MetadataRecord


class SubIssue:
    """A part of an Issue with its own id, status and place among its siblings (spec §12.2).

    A SubIssue lives inside its Issue's aggregate. Its parent is the Issue itself or
    another SubIssue of the same Issue, so SubIssues form a tree. The Issue checks the
    tree; a SubIssue alone only checks its own fields.
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

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SubIssue) and other.sub_issue_id == self._sub_issue_id

    def __hash__(self) -> int:
        return hash(self._sub_issue_id)


def _require_text(**values: str) -> None:
    for field, value in values.items():
        if not value.strip():
            raise IssueFieldEmptyError(field=field)
