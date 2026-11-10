"""Read-only queries the CLI and the API share: ingestion status with its duplicate flags,
extracted content, chunks and what the pipeline page shows (ADR 0008)."""

from dataclasses import dataclass

from offline_rag.knowledge.application.ports import (
    DuplicateFlagRepository,
    ExtractedContentRepository,
    IngestionQueueDepth,
    IngestionQueueMonitor,
    KnowledgeChunkRepository,
    KnowledgeIngestionRepository,
    KnowledgeIngestionSummary,
    KnowledgeItemRepository,
    NodeDirectory,
    Outbox,
)
from offline_rag.knowledge.domain.duplicate_detection import DuplicateFlag
from offline_rag.knowledge.domain.extracted_content import ExtractedContent
from offline_rag.knowledge.domain.knowledge_chunk import KnowledgeChunk
from offline_rag.knowledge.domain.knowledge_ingestion import KnowledgeIngestion
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.shared_kernel.node_identifier import NodeIdentifier


@dataclass(frozen=True, kw_only=True)
class IngestionStatusView:
    """An ingestion with the duplicate flags of the version it reads.

    Attributes:
        ingestion: The run.
        duplicate_flags: The flags of its version, read-only. Empty until a check found one.
    """

    ingestion: KnowledgeIngestion
    duplicate_flags: list[DuplicateFlag]


@dataclass(frozen=True, kw_only=True)
class VersionChunks:
    """The chunks of one version and whether retrieval may use them.

    Attributes:
        version_tag: The version the chunks belong to.
        active_version_tag: The item's active version.
        chunks: The chunks in order.
    """

    version_tag: VersionTag
    active_version_tag: VersionTag
    chunks: list[KnowledgeChunk]

    @property
    def is_retrievable(self) -> bool:
        """Whether the chunks may be retrieved: only those of the active version (spec §7.6)."""
        return self.version_tag == self.active_version_tag


class KnowledgeIngestionQueries:
    """Answers questions about ingestions without changing anything."""

    def __init__(
        self,
        *,
        ingestion_repository: KnowledgeIngestionRepository,
        repository: KnowledgeItemRepository,
        extracted_content_repository: ExtractedContentRepository,
        chunk_repository: KnowledgeChunkRepository,
        duplicate_flag_repository: DuplicateFlagRepository,
        outbox: Outbox,
        node_directory: NodeDirectory,
        queue_monitor: IngestionQueueMonitor,
    ) -> None:
        """Create the queries with the stores they read."""
        self._ingestion_repository = ingestion_repository
        self._repository = repository
        self._extracted_content_repository = extracted_content_repository
        self._chunk_repository = chunk_repository
        self._duplicate_flag_repository = duplicate_flag_repository
        self._outbox = outbox
        self._node_directory = node_directory
        self._queue_monitor = queue_monitor

    def get_ingestion(self, ingestion_id: str) -> IngestionStatusView:
        """Return an ingestion with its status and the duplicate flags of its version.

        Raises:
            KnowledgeIngestionNotFoundError: The ingestion does not exist.
        """
        ingestion = self._ingestion_repository.get_by_id(ingestion_id)
        return IngestionStatusView(
            ingestion=ingestion,
            duplicate_flags=self._duplicate_flag_repository.list_by_version(
                ingestion.item_id, ingestion.version_tag
            ),
        )

    def get_chunks(self, item_id: str, version_tag: VersionTag | None = None) -> VersionChunks:
        """Return the chunks of a version, the active one when none is given.

        Raises:
            KnowledgeItemNotFoundError: The item does not exist.
            KnowledgeVersionNotFoundError: The item has no such version.
        """
        item = self._repository.get_by_id(item_id)
        version = item.get_version(version_tag) if version_tag else item.active_version
        return VersionChunks(
            version_tag=version.version_tag,
            active_version_tag=item.active_version.version_tag,
            chunks=self._chunk_repository.list_by_version(item.item_id, version.version_tag),
        )

    def get_content(
        self, item_id: str, version_tag: VersionTag | None = None
    ) -> tuple[VersionTag, ExtractedContent]:
        """Return the content extracted from a version, the active one when none is given.

        Raises:
            KnowledgeItemNotFoundError: The item does not exist.
            KnowledgeVersionNotFoundError: The item has no such version.
            ExtractedContentNotFoundError: Nothing was extracted from the version yet.
        """
        item = self._repository.get_by_id(item_id)
        version = item.get_version(version_tag) if version_tag else item.active_version
        return version.version_tag, self._extracted_content_repository.get(
            item.item_id, version.version_tag
        )

    def list_recent_ingestions(self, limit: int) -> list[KnowledgeIngestionSummary]:
        """Return up to `limit` ingestions with their file, the most recently created first."""
        return self._ingestion_repository.find_recent(limit)

    def get_queue_depths(self) -> list[IngestionQueueDepth]:
        """Return how many messages each ingestion queue of the broker holds.

        Raises:
            QueueMonitorUnavailableError: The broker's management API cannot be read.
        """
        return self._queue_monitor.get_queue_depths()

    def count_unpublished_messages(self) -> int:
        """Return how many outbox messages wait for the relay."""
        return self._outbox.count_unpublished()

    def list_node_ids(self) -> list[NodeIdentifier]:
        """Return the ids of all registered Nodes, sorted, to pick an owner from.

        Raises:
            NodeRegistryUnavailableError: The Node registry cannot be read.
        """
        return self._node_directory.list_node_ids()
