"""Use case: the outbox relay, which hands stored messages to the broker (ADR 0005)."""

import structlog

from offline_rag.knowledge.application.commands import PublishOutboxMessages
from offline_rag.knowledge.application.ports import Clock, IngestionMessagePublisher, Outbox

log = structlog.get_logger()


class PublishOutboxMessagesHandler:
    """Publishes unpublished outbox messages oldest first and marks each one published.

    Run one relay at a time. Two would read the same rows and publish them twice.
    """

    def __init__(
        self, *, outbox: Outbox, publisher: IngestionMessagePublisher, clock: Clock
    ) -> None:
        """Create the handler with the ports it needs."""
        self._outbox = outbox
        self._publisher = publisher
        self._clock = clock

    def publish(self, command: PublishOutboxMessages) -> int:
        """Publish one batch of waiting messages and return how many were published.

        A message is marked only after the broker stored it, so a crash in between
        sends it twice. Workers tolerate that, because every step is idempotent.

        Raises:
            MessageBrokerUnavailableError: The broker failed. Messages published
                before it stay marked; the rest wait for the next pass.
            KnowledgeStorageError: The database cannot be read or written.
        """
        messages = self._outbox.find_unpublished(command.max_messages)
        for message in messages:
            self._publisher.publish(message)
            self._outbox.mark_published(message.outbox_id, self._clock.now())
            log.debug(
                "outbox_message_published",
                outbox_id=message.outbox_id,
                ingestion_id=message.ingestion_id,
                lane=message.lane.value,
            )
        if messages:
            log.info("outbox_messages_published", count=len(messages))
        return len(messages)
