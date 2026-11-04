"""What submitting and reingesting share: a queued KnowledgeIngestion and its first message."""

from dataclasses import dataclass

from offline_rag.knowledge.application.ports import Clock, IdGenerator, IngestionLane, OutboxMessage
from offline_rag.knowledge.domain.knowledge_ingestion import IngestionStatus, KnowledgeIngestion
from offline_rag.knowledge.domain.version_tag import VersionTag


@dataclass(frozen=True, kw_only=True)
class IngestionReceipt:
    """What a caller gets back once a version is queued for ingestion.

    Attributes:
        item_id: The KnowledgeItem.
        version_tag: The version being ingested.
        ingestion_id: The run to follow with the status query.
        status: The status of the run when it was queued.
    """

    item_id: str
    version_tag: VersionTag
    ingestion_id: str
    status: IngestionStatus


def queue_ingestion(
    *,
    item_id: str,
    version_tag: VersionTag,
    request_id: str | None,
    clock: Clock,
    id_generator: IdGenerator,
) -> tuple[KnowledgeIngestion, OutboxMessage]:
    """Return a new queued run for a version and the message that sends it to a text worker."""
    now = clock.now()
    ingestion = KnowledgeIngestion.queue(
        ingestion_id=id_generator.new_id(),
        item_id=item_id,
        version_tag=version_tag,
        queued_at=now,
        request_id=request_id,
    )
    return ingestion, next_step_message(
        ingestion, IngestionLane.TEXT, clock=clock, id_generator=id_generator
    )


def next_step_message(
    ingestion: KnowledgeIngestion, lane: IngestionLane, *, clock: Clock, id_generator: IdGenerator
) -> OutboxMessage:
    """Return the message that hands an ingestion to the workers of `lane`."""
    return OutboxMessage(
        outbox_id=id_generator.new_id(),
        ingestion_id=ingestion.ingestion_id,
        lane=lane,
        created_at=clock.now(),
    )


def receipt_for(ingestion: KnowledgeIngestion) -> IngestionReceipt:
    """Return the receipt that describes an ingestion."""
    return IngestionReceipt(
        item_id=ingestion.item_id,
        version_tag=ingestion.version_tag,
        ingestion_id=ingestion.ingestion_id,
        status=ingestion.status,
    )
