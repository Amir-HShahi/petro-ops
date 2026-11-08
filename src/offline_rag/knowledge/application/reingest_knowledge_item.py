"""Use case: run the ingestion of a KnowledgeVersion again (ADR 0006)."""

import structlog

from offline_rag.knowledge.application.commands import ReingestKnowledgeItem
from offline_rag.knowledge.application.errors import IngestionAlreadyRunningError
from offline_rag.knowledge.application.ingestion_queueing import (
    IngestionReceipt,
    queue_ingestion,
    receipt_for,
)
from offline_rag.knowledge.application.ports import (
    Clock,
    IdGenerator,
    KnowledgeIngestionRepository,
    KnowledgeItemRepository,
)

log = structlog.get_logger()


class ReingestKnowledgeItemHandler:
    """Queues a new ingestion for a version that was ingested before, for example after a fix."""

    def __init__(
        self,
        *,
        ingestion_repository: KnowledgeIngestionRepository,
        repository: KnowledgeItemRepository,
        clock: Clock,
        id_generator: IdGenerator,
    ) -> None:
        """Create the handler with the ports it needs."""
        self._ingestion_repository = ingestion_repository
        self._repository = repository
        self._clock = clock
        self._id_generator = id_generator

    def reingest(self, command: ReingestKnowledgeItem) -> IngestionReceipt:
        """Queue the version again and return the new ingestion.

        Raises:
            KnowledgeItemNotFoundError: The item does not exist.
            KnowledgeVersionNotFoundError: The item has no such version.
            IngestionAlreadyRunningError: An earlier run of the version has not ended,
                and two runs would overwrite each other's blocks.
        """
        item = self._repository.get_by_id(command.item_id)
        version = (
            item.get_version(command.version_tag) if command.version_tag else item.active_version
        )
        running = self._ingestion_repository.find_running(item.item_id, version.version_tag)
        if running is not None:
            raise IngestionAlreadyRunningError(
                item_id=item.item_id,
                version_tag=version.version_tag.value,
                ingestion_id=running.ingestion_id,
            )

        ingestion, message = queue_ingestion(
            item_id=item.item_id,
            version_tag=version.version_tag,
            request_id=command.request_id,
            clock=self._clock,
            id_generator=self._id_generator,
        )
        self._ingestion_repository.add(ingestion, message)
        log.info(
            "knowledge_item_reingested",
            ingestion_id=ingestion.ingestion_id,
            item_id=item.item_id,
            node_id=item.owner_node_id.value,
            version_tag=version.version_tag.value,
        )
        return receipt_for(ingestion)
