"""The `IngestionMessagePublisher` port on the local RabbitMQ broker (ADR 0005)."""

import contextlib

import pika
from pika.adapters.blocking_connection import BlockingChannel, BlockingConnection
from pika.exceptions import AMQPError

from offline_rag.knowledge.application.ports import OutboxMessage
from offline_rag.knowledge.infrastructure.errors import MessageBrokerUnavailableError
from offline_rag.knowledge.infrastructure.rabbitmq_topology import (
    INGESTION_EXCHANGE,
    declare_ingestion_topology,
    message_body,
    message_properties,
)


class RabbitMqIngestionMessagePublisher:
    """Publishes persistent messages with publisher confirms, on one lazily opened connection.

    A failed connection is dropped and opened again on the next publish.
    """

    def __init__(self, url: str) -> None:
        """Create the publisher. Nothing connects until the first message.

        Args:
            url: An AMQP URL on a loopback host.
        """
        self._parameters = pika.URLParameters(url)
        self._connection: BlockingConnection | None = None
        self._channel: BlockingChannel | None = None

    def publish(self, message: OutboxMessage) -> None:
        """Publish the message to its lane and return once the broker has stored it.

        Raises:
            MessageBrokerUnavailableError: The broker cannot be reached, refused
                the message, or has no queue for its lane.
        """
        try:
            # `mandatory` makes a message no queue takes fail here instead of vanishing.
            self._open_channel().basic_publish(
                INGESTION_EXCHANGE,
                message.lane.value,
                message_body(ingestion_id=message.ingestion_id, outbox_id=message.outbox_id),
                message_properties(outbox_id=message.outbox_id, attempt=1),
                mandatory=True,
            )
        except AMQPError as error:
            self.close()
            operation = "publish"
            raise MessageBrokerUnavailableError(operation) from error

    def close(self) -> None:
        """Close the connection, if one is open."""
        connection, self._connection, self._channel = self._connection, None, None
        if connection is not None and connection.is_open:
            # A broken connection may fail to close; there is nothing left to free then.
            with contextlib.suppress(AMQPError):
                connection.close()

    def _open_channel(self) -> BlockingChannel:
        if self._channel is None or not self._channel.is_open:
            self.close()
            self._connection = BlockingConnection(self._parameters)
            self._channel = self._connection.channel()
            declare_ingestion_topology(self._channel)
            self._channel.confirm_delivery()
        return self._channel
