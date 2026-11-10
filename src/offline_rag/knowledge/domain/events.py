"""Domain events of Knowledge Management (docs/domain-model.md, section 2)."""

from dataclasses import dataclass

from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.duplicate_detection import DuplicateKind
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.shared_kernel.domain_event import DomainEvent
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier


@dataclass(frozen=True, kw_only=True)
class KnowledgeItemSubmitted(DomainEvent):
    """A new KnowledgeItem was registered with its first version (spec §7.2 step 1)."""

    item_id: str
    owner_node_id: NodeIdentifier
    version_tag: VersionTag
    document_format: DocumentFormat
    content_hash: str


@dataclass(frozen=True, kw_only=True)
class MetadataRecorded(DomainEvent):
    """Metadata was recorded for a version of a KnowledgeItem (spec §7.2 step 2)."""

    item_id: str
    version_tag: VersionTag
    metadata: MetadataRecord


@dataclass(frozen=True, kw_only=True)
class KnowledgeContentExtracted(DomainEvent):
    """Text and structure were extracted from a KnowledgeVersion (spec §7.2 steps 3 and 4).

    Attributes:
        pages_without_text: PDF pages with no usable text layer. The LVM reads them.
    """

    item_id: str
    version_tag: VersionTag
    block_count: int
    pages_without_text: tuple[int, ...]


@dataclass(frozen=True, kw_only=True)
class PagesReadWithLvm(DomainEvent):
    """The LVM read PDF pages that had no text layer (spec §7.3, ADR 0002).

    Attributes:
        page_numbers: The pages that were read.
        tables_for_review: How many scanned tables a person must check.
    """

    item_id: str
    version_tag: VersionTag
    page_numbers: tuple[int, ...]
    tables_for_review: int


@dataclass(frozen=True, kw_only=True)
class KnowledgeVersionPublished(DomainEvent):
    """A new version of a KnowledgeItem became its active version (spec §7.6).

    The chunks of the previous version stop being retrievable from now on.
    """

    item_id: str
    version_tag: VersionTag
    previous_version_tag: VersionTag
    change_reason: str
    document_format: DocumentFormat
    content_hash: str


@dataclass(frozen=True, kw_only=True)
class DuplicateDetected(DomainEvent):
    """A KnowledgeVersion repeats another KnowledgeItem of the same Node (spec §7.7).

    Both items are kept; the event only reports the finding.
    """

    item_id: str
    version_tag: VersionTag
    kind: DuplicateKind
    existing_item_id: str
    existing_version_tag: VersionTag
    score: float
    is_ambiguous: bool
