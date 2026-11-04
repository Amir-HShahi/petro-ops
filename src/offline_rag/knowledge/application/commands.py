"""Inputs of the Knowledge Management use cases."""

from dataclasses import dataclass, field

from offline_rag.knowledge.domain.knowledge_scope import KnowledgeScope
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier


@dataclass(frozen=True, kw_only=True)
class SubmitKnowledgeItem:
    """Register a DOC, DOCX or PDF file as a new KnowledgeItem of a Node.

    Attributes:
        owner_node_id: The Node that owns the knowledge.
        source_file_name: The name of the file, as the user knows it.
        content: The whole file.
        scope: Confidentiality and usage scope of the item.
        metadata: Metadata recorded with the first version.
    """

    owner_node_id: NodeIdentifier
    source_file_name: str
    content: bytes = field(repr=False)
    scope: KnowledgeScope
    metadata: MetadataRecord = field(default_factory=MetadataRecord)
