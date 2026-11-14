"""Inputs of the Issue Management use cases."""

from dataclasses import dataclass

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
