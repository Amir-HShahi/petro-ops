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
