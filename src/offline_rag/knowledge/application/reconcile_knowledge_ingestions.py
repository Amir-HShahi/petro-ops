"""Use case: resend the message of ingestions whose message was lost (ADR 0005)."""

from datetime import timedelta

import structlog

from offline_rag.knowledge.application.commands import ReconcileKnowledgeIngestions
from offline_rag.knowledge.application.ingestion_queueing import next_step_message
from offline_rag.knowledge.application.ports import (
    Clock,
    IdGenerator,
    IngestionLane,
    KnowledgeIngestionRepository,
    Outbox,
)
from offline_rag.knowledge.domain.knowledge_ingestion import IngestionStatus, KnowledgeIngestion

log = structlog.get_logger()

_LANE_BY_STATUS = {
    IngestionStatus.QUEUED: IngestionLane.TEXT,
    IngestionStatus.READING_PAGES: IngestionLane.VISION,
    IngestionStatus.CHUNKING: IngestionLane.CHUNKING,
}


class ReconcileKnowledgeIngestionsHandler:
    """Finds ingestions that waited too long for a worker and adds a fresh message for each.

    A published message can still be lost, for example when the broker loses its
    data or a queue is purged. The ingestion would then wait forever.
    """

    def __init__(
        self,
        *,
        ingestion_repository: KnowledgeIngestionRepository,
        outbox: Outbox,
        clock: Clock,
        id_generator: IdGenerator,
        reconcile_after_s: int,
    ) -> None:
        """Create the handler.

        Args:
            ingestion_repository: Where KnowledgeIngestions are stored.
            outbox: Where the new messages go; the relay publishes them.
            clock: Tells how long an ingestion has waited.
            id_generator: Names the new messages.
            reconcile_after_s: How long an ingestion may wait after its last
                message, in seconds, before it gets a new one. Keep it above the
                longest queue wait, since a message that was only slow then
                arrives twice.
        """
        self._ingestion_repository = ingestion_repository
        self._outbox = outbox
        self._clock = clock
        self._id_generator = id_generator
        self._reconcile_after_s = reconcile_after_s

    def reconcile(self, command: ReconcileKnowledgeIngestions) -> list[KnowledgeIngestion]:
        """Add a new message for each stalled ingestion and return those ingestions.

        The ingestions themselves are not saved, so a worker that moves one at
        the same moment is never overwritten.

        Raises:
            KnowledgeStorageError: The database cannot be read or written.
        """
        stalled_since = self._clock.now() - timedelta(seconds=self._reconcile_after_s)
        stalled = self._ingestion_repository.find_stalled(
            stalled_since, limit=command.max_ingestions
        )
        for ingestion in stalled:
            lane = _LANE_BY_STATUS[ingestion.status]
            self._outbox.add(
                next_step_message(
                    ingestion, lane, clock=self._clock, id_generator=self._id_generator
                )
            )
            log.warning(
                "knowledge_ingestion_message_resent",
                ingestion_id=ingestion.ingestion_id,
                item_id=ingestion.item_id,
                request_id=ingestion.request_id,
                lane=lane.value,
            )
        return stalled
