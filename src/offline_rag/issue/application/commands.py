"""Inputs of the Issue Management use cases."""

from dataclasses import dataclass

from offline_rag.issue.domain.issue_priority import IssuePriority
from offline_rag.issue.domain.issue_status import IssueStatus
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier


@dataclass(frozen=True, kw_only=True)
class RaiseIssue:
    """Define a new Issue for a Node (spec §12.1).

    Attributes:
        owner_node_id: The registered Node the Issue belongs to.
        title: A short name of the Issue.
        description: What the problem is.
        metadata: Its structured metadata (spec §7.5).
    """

    owner_node_id: NodeIdentifier
    title: str
    description: str
    metadata: MetadataRecord


@dataclass(frozen=True, kw_only=True)
class AddSubIssue:
    """Split a part off an Issue, or off one of its SubIssues, by hand (spec §12.2).

    Attributes:
        issue_id: The Issue the SubIssue belongs to.
        parent_id: The SubIssue being split, or None to split the Issue itself.
        title: A short name of the SubIssue.
        description: What the SubIssue is about.
        metadata: Its structured metadata (spec §7.5).
    """

    issue_id: str
    parent_id: str | None
    title: str
    description: str
    metadata: MetadataRecord


@dataclass(frozen=True, kw_only=True)
class DecomposeIssue:
    """Ask the LLM to suggest SubIssues for an Issue, based on chosen knowledge (spec §12.2).

    Attributes:
        issue_id: The Issue to split.
        knowledge_item_ids: The KnowledgeItems whose active chunks the LLM reads and
            cites. At least one.
    """

    issue_id: str
    knowledge_item_ids: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class AcceptSubIssueCandidates:
    """Turn chosen SubIssue candidates into SubIssues of their Issue.

    Attributes:
        issue_id: The Issue the candidates belong to.
        numbers: The candidates to accept, in the order they should be added.
    """

    issue_id: str
    numbers: tuple[int, ...]


@dataclass(frozen=True, kw_only=True)
class SetIssuePriority:
    """Say how urgent an Issue is (spec §12.3, §14.2).

    Attributes:
        issue_id: The Issue.
        priority: Its new priority.
    """

    issue_id: str
    priority: IssuePriority


@dataclass(frozen=True, kw_only=True)
class MoveSubIssue:
    """Move a SubIssue to another place among its siblings (spec §12.2, §12.3).

    Attributes:
        issue_id: The Issue the SubIssue belongs to.
        sub_issue_id: The SubIssue to move.
        position: Its new place, from 1.
    """

    issue_id: str
    sub_issue_id: str
    position: int


@dataclass(frozen=True, kw_only=True)
class AddSubIssueDependency:
    """Make a SubIssue wait for another SubIssue of the same Issue (spec §12.3).

    Attributes:
        issue_id: The Issue both SubIssues belong to.
        sub_issue_id: The SubIssue that waits.
        depends_on_sub_issue_id: The SubIssue it waits for.
    """

    issue_id: str
    sub_issue_id: str
    depends_on_sub_issue_id: str


@dataclass(frozen=True, kw_only=True)
class RemoveSubIssueDependency:
    """Stop a SubIssue waiting for another SubIssue of the same Issue.

    Attributes:
        issue_id: The Issue both SubIssues belong to.
        sub_issue_id: The SubIssue that waits.
        depends_on_sub_issue_id: The SubIssue it no longer waits for.
    """

    issue_id: str
    sub_issue_id: str
    depends_on_sub_issue_id: str


@dataclass(frozen=True, kw_only=True)
class ChangeIssueStatus:
    """Move an Issue, or one of its SubIssues, to another status (spec §14.1).

    Attributes:
        issue_id: The Issue.
        status: The new status.
        sub_issue_id: The SubIssue to change, or None for the Issue itself.
    """

    issue_id: str
    status: IssueStatus
    sub_issue_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class ResolveIssue:
    """Mark an Issue resolved, with how it was solved (spec §12.5, §14.1).

    Attributes:
        issue_id: The Issue.
        resolution_summary: How the problem was solved.
    """

    issue_id: str
    resolution_summary: str
