"""Use case: end an ingestion whose step kept failing (ADR 0005)."""

import structlog

from offline_rag.knowledge.application.commands import FailKnowledgeIngestion
from offline_rag.knowledge.application.ports import Clock, KnowledgeIngestionRepository
from offline_rag.knowledge.domain.knowledge_ingestion import KnowledgeIngestion

log = structlog.get_logger()


class FailKnowledgeIngestionHandler:
    """Marks an ingestion FAILED once its message has used up its retries."""

    def __init__(self, *, ingestion_repository: KnowledgeIngestionRepository, clock: Clock) -> None:
        """Create the handler with the ports it needs."""
        self._ingestion_repository = ingestion_repository
        self._clock = clock

    def fail(self, command: FailKnowledgeIngestion) -> KnowledgeIngestion:
        """End the ingestion as FAILED and return it. A run that has ended stays as it is.

        Raises:
            KnowledgeIngestionNotFoundError: The ingestion does not exist.
        """
        ingestion = self._ingestion_repository.get_by_id(command.ingestion_id)
        if not ingestion.is_running:
            return ingestion

        ingestion.fail(
            failure_code=command.failure_code,
            failure_detail=command.failure_detail,
            now=self._clock.now(),
        )
        self._ingestion_repository.save(ingestion)
        log.warning(
            "knowledge_ingestion_failed",
            ingestion_id=ingestion.ingestion_id,
            item_id=ingestion.item_id,
            code=command.failure_code,
            attempts=ingestion.attempts,
        )
        return ingestion
