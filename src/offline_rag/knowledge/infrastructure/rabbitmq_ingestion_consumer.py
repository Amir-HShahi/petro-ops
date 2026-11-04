"""A worker's connection to one ingestion queue on the local RabbitMQ broker (ADR 0005)."""

import functools
import json
import threading
from collections.abc import Callable
from typing import Any

import pika
import structlog
from pika.adapters.blocking_connection import BlockingChannel, BlockingConnection
from pika.exceptions import AMQPError
from pika.spec import Basic, BasicProperties

from offline_rag.knowledge.application.commands import RunIngestionStep
from offline_rag.knowledge.application.ports import IngestionLane
from offline_rag.knowledge.application.run_ingestion_step import IngestionStepOutcome
from offline_rag.knowledge.infrastructure.errors import MessageBrokerUnavailableError
from offline_rag.knowledge.infrastructure.rabbitmq_topology import (
    ATTEMPT_HEADER,
    DEAD_LETTER_QUEUE,
    QUEUE_BY_LANE,
    RETRY_EXCHANGE,
    declare_ingestion_topology,
    message_properties,
)

log = structlog.get_logger()

RunStep = Callable[[RunIngestionStep], IngestionStepOutcome]


class RabbitMqIngestionConsumer:
    """Takes messages from the queue of one lane and settles each one by its step's outcome.

    The step runs on its own thread while this thread keeps the connection alive,
    so a long step does not miss heartbeats. A message is acked only after the
    step has returned, so its results are already committed.
    """

    def __init__(
        self, url: str, *, lane: IngestionLane, prefetch_count: int, retry_delay_s: int
    ) -> None:
        """Create the consumer. Nothing connects until `run`.

        Args:
            url: An AMQP URL on a loopback host.
            lane: The queue to take messages from.
            prefetch_count: How many unacked messages the broker sends at once.
            retry_delay_s: How long a message waits in the retry queue.
        """
        self._parameters = pika.URLParameters(url)
        self._lane = lane
        self._prefetch_count = prefetch_count
        self._retry_delay_ms = retry_delay_s * 1000
        self._connection: BlockingConnection | None = None
        self._channel: BlockingChannel | None = None

    def run(self, run_step: RunStep) -> None:
        """Consume messages until `stop` is called.

        Args:
            run_step: Runs one step and returns its outcome. It must not raise:
                a message whose step raised would stay unacked until the
                connection closes.

        Raises:
            MessageBrokerUnavailableError: The broker cannot be reached or the
                connection broke. Unacked messages go back to the queue.
        """
        try:
            self._connection = BlockingConnection(self._parameters)
            self._channel = self._connection.channel()
            declare_ingestion_topology(self._channel)
            self._channel.confirm_delivery()
            self._channel.basic_qos(prefetch_count=self._prefetch_count)
            self._channel.basic_consume(
                QUEUE_BY_LANE[self._lane],
                functools.partial(self._on_message, run_step=run_step),
            )
            log.info("ingestion_worker_started", lane=self._lane.value)
            self._channel.start_consuming()
        except AMQPError as error:
            operation = "consume"
            raise MessageBrokerUnavailableError(operation) from error
        finally:
            self._close()

    def stop(self) -> None:
        """Stop consuming after the message in hand is settled. Safe from any thread."""
        connection, channel = self._connection, self._channel
        if connection is not None and channel is not None and connection.is_open:
            connection.add_callback_threadsafe(channel.stop_consuming)

    def _on_message(
        self,
        channel: BlockingChannel,
        method: Basic.Deliver,
        properties: BasicProperties,
        body: bytes,
        *,
        run_step: RunStep,
    ) -> None:
        try:
            command = self._command(method, properties, body)
        except (ValueError, KeyError, TypeError):
            log.warning(
                "ingestion_message_dead_lettered", lane=self._lane.value, reason="malformed"
            )
            self._dead_letter(channel, properties, body, reason="malformed")
            channel.basic_ack(method.delivery_tag)
            return
        threading.Thread(
            target=self._run_off_connection_thread,
            args=(channel, method, properties, body, command, run_step),
            daemon=True,
        ).start()

    def _run_off_connection_thread(
        self,
        channel: BlockingChannel,
        method: Basic.Deliver,
        properties: BasicProperties,
        body: bytes,
        command: RunIngestionStep,
        run_step: RunStep,
    ) -> None:
        outcome = run_step(command)
        # pika channels are not thread-safe, so the message is settled on the
        # connection's own thread.
        assert self._connection is not None
        self._connection.add_callback_threadsafe(
            functools.partial(self._settle, channel, method, properties, body, command, outcome)
        )

    def _settle(
        self,
        channel: BlockingChannel,
        method: Basic.Deliver,
        properties: BasicProperties,
        body: bytes,
        command: RunIngestionStep,
        outcome: IngestionStepOutcome,
    ) -> None:
        match outcome:
            case IngestionStepOutcome.RETRY:
                channel.basic_publish(
                    RETRY_EXCHANGE,
                    self._lane.value,
                    body,
                    message_properties(
                        outbox_id=properties.message_id,
                        attempt=command.attempt + 1,
                        expiration_ms=self._retry_delay_ms,
                    ),
                    mandatory=True,
                )
            case IngestionStepOutcome.GIVE_UP:
                self._dead_letter(channel, properties, body, reason="attempts_used_up")
            case IngestionStepOutcome.DONE:
                pass
        channel.basic_ack(method.delivery_tag)

    def _dead_letter(
        self, channel: BlockingChannel, properties: BasicProperties, body: bytes, *, reason: str
    ) -> None:
        headers: dict[str, Any] = dict(properties.headers or {})
        channel.basic_publish(
            "",
            DEAD_LETTER_QUEUE,
            body,
            message_properties(
                outbox_id=properties.message_id,
                attempt=int(headers.get(ATTEMPT_HEADER, 1)),
                lane=self._lane.value,
                dead_letter_reason=reason,
            ),
            mandatory=True,
        )

    def _command(
        self, method: Basic.Deliver, properties: BasicProperties, body: bytes
    ) -> RunIngestionStep:
        payload = json.loads(body)
        attempt = int((properties.headers or {}).get(ATTEMPT_HEADER, 1))
        return RunIngestionStep(
            ingestion_id=str(payload["ingestion_id"]),
            lane=self._lane,
            attempt=attempt,
            is_redelivery=bool(method.redelivered),
        )

    def _close(self) -> None:
        connection, self._connection, self._channel = self._connection, None, None
        if connection is not None and connection.is_open:
            try:
                connection.close()
            except AMQPError:
                log.debug("ingestion_worker_connection_already_closed", lane=self._lane.value)
