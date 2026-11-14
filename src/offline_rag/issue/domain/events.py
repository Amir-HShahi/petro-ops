"""Domain events of Issue Management (docs/domain-model.md, section 4)."""

from dataclasses import dataclass

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
