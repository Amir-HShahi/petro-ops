"""The ingestion worker process: runs the steps of one lane until stopped (ADR 0005)."""

import signal
import time
from types import FrameType

import structlog

from offline_rag.bootstrap import build_ingestion_consumer, build_knowledge, configure_logging
from offline_rag.knowledge.application.commands import FailKnowledgeIngestion, RunIngestionStep
from offline_rag.knowledge.application.fail_knowledge_ingestion import (
    FailKnowledgeIngestionHandler,
)
from offline_rag.knowledge.application.ports import IngestionLane
from offline_rag.knowledge.application.run_ingestion_step import (
    IngestionStepOutcome,
    RunIngestionStepHandler,
)
from offline_rag.knowledge.infrastructure.errors import MessageBrokerUnavailableError
from offline_rag.knowledge.infrastructure.rabbitmq_ingestion_consumer import RunStep
from offline_rag.knowledge.interface.problem_details import UNEXPECTED_CODE
from offline_rag.settings import Settings
from offline_rag.shared_kernel.errors import ProjectError

log = structlog.get_logger()

UNEXPECTED_DETAIL = "Something went wrong inside the core. Report it with the ingestion id."


def run_worker(lane: IngestionLane, settings: Settings) -> None:
    """Consume the queue of `lane` until SIGTERM or SIGINT, reconnecting when the broker drops."""
    configure_logging(settings)
    knowledge = build_knowledge(settings)
    consumer = build_ingestion_consumer(settings, lane)
    is_stopping = False

    def stop(signal_number: int, frame: FrameType | None) -> None:
        nonlocal is_stopping
        is_stopping = True
        consumer.stop()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    run_step = guard_step(knowledge.run_step_handler, knowledge.fail_handler)
    try:
        while not is_stopping:
            try:
                consumer.run(run_step)
            except MessageBrokerUnavailableError as error:
                if is_stopping:
                    break
                log.warning(
                    "ingestion_worker_reconnecting",
                    lane=lane.value,
                    code=error.code,
                    delay_s=settings.worker_retry_delay_s,
                )
                time.sleep(settings.worker_retry_delay_s)
    finally:
        knowledge.close()
        log.info("ingestion_worker_stopped", lane=lane.value)


def guard_step(
    run_handler: RunIngestionStepHandler, fail_handler: FailKnowledgeIngestionHandler
) -> RunStep:
    """Return a step runner that never raises, as the consumer requires.

    An error the use case does not handle is a bug. Its ingestion is marked FAILED
    and its message goes to the dead-letter queue, so the worker moves on.
    """

    def run_step(command: RunIngestionStep) -> IngestionStepOutcome:
        structlog.contextvars.bind_contextvars(
            ingestion_id=command.ingestion_id, lane=command.lane.value, attempt=command.attempt
        )
        try:
            return run_handler.run(command)
        except Exception:
            log.exception("ingestion_step_failed", code=UNEXPECTED_CODE)
            _fail_after_bug(fail_handler, command)
            return IngestionStepOutcome.GIVE_UP
        finally:
            structlog.contextvars.clear_contextvars()

    return run_step


def _fail_after_bug(fail_handler: FailKnowledgeIngestionHandler, command: RunIngestionStep) -> None:
    try:
        fail_handler.fail(
            FailKnowledgeIngestion(
                ingestion_id=command.ingestion_id,
                failure_code=UNEXPECTED_CODE,
                failure_detail=UNEXPECTED_DETAIL,
            )
        )
    except ProjectError:
        # The run stays open; its message in the dead-letter queue can be replayed.
        log.exception("ingestion_not_marked_failed", code=UNEXPECTED_CODE)
