"""Use case: run one worker step of a KnowledgeIngestion and decide on retries (ADR 0005)."""

from enum import StrEnum

import structlog

from offline_rag.knowledge.application.commands import (
    ExtractKnowledgeContent,
    FailKnowledgeIngestion,
    ReadPagesWithLvm,
    RunIngestionStep,
)
from offline_rag.knowledge.application.errors import KnowledgeIngestionNotFoundError
from offline_rag.knowledge.application.extract_knowledge_content import (
    ExtractKnowledgeContentHandler,
)
from offline_rag.knowledge.application.fail_knowledge_ingestion import (
    FailKnowledgeIngestionHandler,
)
from offline_rag.knowledge.application.ports import IngestionLane
from offline_rag.knowledge.application.read_pages_with_lvm import ReadPagesWithLvmHandler
from offline_rag.shared_kernel.errors import InfrastructureError

log = structlog.get_logger()


class IngestionStepOutcome(StrEnum):
    """What the worker does with the message once the step has run."""

    DONE = "done"
    """Ack it: the step ran, or there was nothing left to do."""
    RETRY = "retry"
    """Send it to the retry queue, to run again after `WORKER_RETRY_DELAY_S`."""
    GIVE_UP = "give_up"
    """Send it to the dead-letter queue; the ingestion has been marked FAILED."""


class RunIngestionStepHandler:
    """Routes a message to extraction or page reading, and retries what a retry can fix.

    Errors a retry cannot fix, such as a damaged file, are already handled by the
    steps, which end the ingestion as FAILED. Here only infrastructure errors are
    left: a model, store, broker or the database that is down for a while.
    """

    def __init__(
        self,
        *,
        extract_handler: ExtractKnowledgeContentHandler,
        read_pages_handler: ReadPagesWithLvmHandler,
        fail_handler: FailKnowledgeIngestionHandler,
        max_attempts: int,
    ) -> None:
        """Create the handler.

        Args:
            extract_handler: Runs the text lane step.
            read_pages_handler: Runs the vision lane step.
            fail_handler: Ends an ingestion whose retries are used up.
            max_attempts: How many times a step is tried before the ingestion fails.
        """
        self._extract_handler = extract_handler
        self._read_pages_handler = read_pages_handler
        self._fail_handler = fail_handler
        self._max_attempts = max_attempts

    def run(self, command: RunIngestionStep) -> IngestionStepOutcome:
        """Run the step and return what to do with its message.

        Raises:
            KnowledgeStorageError: The database failed while the ingestion was
                being marked FAILED, so its message cannot be settled yet.
        """
        try:
            self._run_step(command)
        except KnowledgeIngestionNotFoundError:
            log.warning("ingestion_step_dropped", ingestion_id=command.ingestion_id)
            return IngestionStepOutcome.DONE
        except InfrastructureError as error:
            if command.attempt < self._max_attempts:
                log.warning(
                    "ingestion_step_retried",
                    ingestion_id=command.ingestion_id,
                    lane=command.lane.value,
                    attempt=command.attempt,
                    code=error.code,
                )
                return IngestionStepOutcome.RETRY
            self._fail_handler.fail(
                FailKnowledgeIngestion(
                    ingestion_id=command.ingestion_id,
                    failure_code=error.code,
                    failure_detail=error.message,
                )
            )
            return IngestionStepOutcome.GIVE_UP
        return IngestionStepOutcome.DONE

    def _run_step(self, command: RunIngestionStep) -> None:
        match command.lane:
            case IngestionLane.TEXT:
                self._extract_handler.extract(
                    ExtractKnowledgeContent(
                        ingestion_id=command.ingestion_id,
                        is_redelivery=command.is_redelivery or command.attempt > 1,
                    )
                )
            case IngestionLane.VISION:
                self._read_pages_handler.read(ReadPagesWithLvm(ingestion_id=command.ingestion_id))
