"""Read-only queries the CLI and the API share: ingestion status and extracted content."""

from offline_rag.knowledge.application.ports import (
    ExtractedContentRepository,
    KnowledgeIngestionRepository,
    KnowledgeItemRepository,
)
from offline_rag.knowledge.domain.extracted_content import ExtractedContent
from offline_rag.knowledge.domain.knowledge_ingestion import KnowledgeIngestion
from offline_rag.knowledge.domain.version_tag import VersionTag


class KnowledgeIngestionQueries:
    """Answers questions about ingestions without changing anything."""

    def __init__(
        self,
        *,
        ingestion_repository: KnowledgeIngestionRepository,
        repository: KnowledgeItemRepository,
        extracted_content_repository: ExtractedContentRepository,
    ) -> None:
        """Create the queries with the stores they read."""
        self._ingestion_repository = ingestion_repository
        self._repository = repository
        self._extracted_content_repository = extracted_content_repository

    def get_ingestion(self, ingestion_id: str) -> KnowledgeIngestion:
        """Return an ingestion with its status.

        Raises:
            KnowledgeIngestionNotFoundError: The ingestion does not exist.
        """
        return self._ingestion_repository.get_by_id(ingestion_id)

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
