"""Domain events of Issue Management (docs/domain-model.md, section 4)."""

from dataclasses import dataclass

from offline_rag.issue.domain.issue_priority import IssuePriority
from offline_rag.issue.domain.issue_status import IssueStatus
from offline_rag.issue.domain.similar_issue import SimilarIssueKind
from offline_rag.shared_kernel.domain_event import DomainEvent
from offline_rag.shared_kernel.node_identifier import NodeIdentifier


@dataclass(frozen=True, kw_only=True)
class IssueRaised(DomainEvent):
    """A Node defined a new Issue (spec §12.1)."""

    issue_id: str
    owner_node_id: NodeIdentifier


@dataclass(frozen=True, kw_only=True)
class SimilarIssueFound(DomainEvent):
    """A new Issue looks like an existing Issue of the same Node (spec §12.1, step 4).

    Attributes:
        score: The word similarity of the two texts, from 0 to 1.
    """

    issue_id: str
    similar_issue_id: str
    kind: SimilarIssueKind
    score: float


@dataclass(frozen=True, kw_only=True)
class SubIssueAdded(DomainEvent):
    """A SubIssue was split off an Issue or off another SubIssue by hand (spec §12.2).

    Attributes:
        parent_id: The Issue id, or the id of the SubIssue it was split from.
        position: Its place among the SubIssues of that parent, from 1.
    """

    issue_id: str
    sub_issue_id: str
    parent_id: str
    position: int


@dataclass(frozen=True, kw_only=True)
class IssueDecomposed(DomainEvent):
    """A person accepted SubIssue candidates the LLM suggested for an Issue (spec §12.2).

    Attributes:
        sub_issue_ids: The new SubIssues, in the order they were added.
    """

    issue_id: str
    sub_issue_ids: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class IssuePrioritized(DomainEvent):
    """A person set how urgent an Issue is (spec §12.3, §14.2)."""

    issue_id: str
    priority: IssuePriority


@dataclass(frozen=True, kw_only=True)
class SubIssueMoved(DomainEvent):
    """A SubIssue moved to another place among its siblings (spec §12.2, §12.3).

    Attributes:
        position: Its new place, from 1. The siblings after it moved along.
    """

    issue_id: str
    sub_issue_id: str
    position: int


@dataclass(frozen=True, kw_only=True)
class SubIssueDependencyAdded(DomainEvent):
    """A SubIssue now waits for another SubIssue of the same Issue (spec §12.3)."""

    issue_id: str
    sub_issue_id: str
    depends_on_sub_issue_id: str


@dataclass(frozen=True, kw_only=True)
class SubIssueDependencyRemoved(DomainEvent):
    """A SubIssue no longer waits for another SubIssue of the same Issue."""

    issue_id: str
    sub_issue_id: str
    depends_on_sub_issue_id: str


@dataclass(frozen=True, kw_only=True)
class IssueStatusChanged(DomainEvent):
    """An Issue, or one of its SubIssues, moved to another status (spec §14.1).

    Attributes:
        sub_issue_id: The SubIssue that changed, or None when the Issue itself did.
    """

    issue_id: str
    sub_issue_id: str | None
    previous_status: IssueStatus
    status: IssueStatus


@dataclass(frozen=True, kw_only=True)
class IssueResolved(DomainEvent):
    """An Issue was resolved; Knowledge Management may store its resolution (spec §8.1).

    Attributes:
        resolution_summary: How the problem was solved, as the person wrote it.
    """

    issue_id: str
    owner_node_id: NodeIdentifier
    resolution_summary: str
