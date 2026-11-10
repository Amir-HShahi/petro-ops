"""Inputs of the Knowledge Management use cases."""

from dataclasses import dataclass, field

from offline_rag.knowledge.application.ports import IngestionLane
from offline_rag.knowledge.domain.knowledge_scope import KnowledgeScope
from offline_rag.knowledge.domain.version_tag import VersionTag
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
    request_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class ExtractKnowledgeContent:
    """Extract the text and structure of the version an ingestion is for (spec §7.2 steps 3, 4).

    Attributes:
        ingestion_id: The KnowledgeIngestion. Running it again replaces the old result.
        is_redelivery: Whether the message comes again after a worker stopped or a
            step failed. Only then may a run that is already EXTRACTING start over;
            otherwise another worker is still on it.
    """

    ingestion_id: str
    is_redelivery: bool = False


@dataclass(frozen=True, kw_only=True)
class ReadPagesWithLvm:
    """Read the PDF pages without a text layer with the LVM (spec §7.3, ADR 0002).

    Attributes:
        ingestion_id: The KnowledgeIngestion, which must be waiting for page reading.
        page_numbers: The pages to read. None means every page without a text layer.
    """

    ingestion_id: str
    page_numbers: tuple[int, ...] | None = None


@dataclass(frozen=True, kw_only=True)
class PublishKnowledgeVersion:
    """Publish a new file as the next, active version of a KnowledgeItem (spec §7.6).

    Attributes:
        item_id: The KnowledgeItem.
        source_file_name: The name of the new file, as the user knows it.
        content: The whole new file.
        change_reason: Why the item changed, in a sentence.
        metadata: Metadata of the new version. None keeps the active version's metadata.
        diff_summary: Optional short summary of what changed.
        request_id: The request that asked for it, for tracing logs.
    """

    item_id: str
    source_file_name: str
    content: bytes = field(repr=False)
    change_reason: str
    metadata: MetadataRecord | None = None
    diff_summary: str | None = None
    request_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class ChunkKnowledgeContent:
    """Cut the stored content of an ingestion's version into chunks and check for duplicates.

    Spec §7.2 steps 5 and 7, §7.4, §7.7.

    Attributes:
        ingestion_id: The KnowledgeIngestion, which must be waiting for chunking.
    """

    ingestion_id: str


@dataclass(frozen=True, kw_only=True)
class ReingestKnowledgeItem:
    """Run the ingestion of a KnowledgeVersion again, for example after a parser fix.

    Attributes:
        item_id: The KnowledgeItem.
        version_tag: The version to ingest. None means the active version.
        request_id: The request that asked for it, for tracing logs.
    """

    item_id: str
    version_tag: VersionTag | None = None
    request_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class RunIngestionStep:
    """Run the step a worker message asks for, and decide what happens to the message.

    Attributes:
        ingestion_id: The KnowledgeIngestion the message is for.
        lane: The queue the message came from, which names the step.
        attempt: How many times this step has been tried, counting this one.
        is_redelivery: Whether the broker delivered the message again because the
            worker that had it stopped before acking.
    """

    ingestion_id: str
    lane: IngestionLane
    attempt: int = 1
    is_redelivery: bool = False


@dataclass(frozen=True, kw_only=True)
class PublishOutboxMessages:
    """Publish the outbox messages the broker does not have yet, oldest first (ADR 0005).

    Attributes:
        max_messages: The most messages one pass publishes.
    """

    max_messages: int = 100


@dataclass(frozen=True, kw_only=True)
class ReconcileKnowledgeIngestions:
    """Send a new message for ingestions that stopped because their message was lost (ADR 0005).

    Attributes:
        max_ingestions: The most ingestions one pass sends a message for.
    """

    max_ingestions: int = 100


@dataclass(frozen=True, kw_only=True)
class FailKnowledgeIngestion:
    """End an ingestion whose step kept failing (ADR 0005, `WORKER_MAX_ATTEMPTS`).

    Attributes:
        ingestion_id: The KnowledgeIngestion.
        failure_code: The code of the last error.
        failure_detail: A short description of the last error.
    """

    ingestion_id: str
    failure_code: str
    failure_detail: str
