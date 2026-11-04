"""The outbox relay process: reconciles and publishes outbox messages until stopped (ADR 0005)."""

import signal
import threading
from types import FrameType

import structlog

from offline_rag.bootstrap import build_knowledge, configure_logging
from offline_rag.knowledge.application.commands import (
    PublishOutboxMessages,
    ReconcileKnowledgeIngestions,
)
from offline_rag.knowledge.application.publish_outbox_messages import (
    PublishOutboxMessagesHandler,
)
from offline_rag.knowledge.application.reconcile_knowledge_ingestions import (
    ReconcileKnowledgeIngestionsHandler,
)
from offline_rag.settings import Settings
from offline_rag.shared_kernel.errors import InfrastructureError

log = structlog.get_logger()


def run_relay(settings: Settings) -> None:
    """Run a relay pass every `OUTBOX_POLL_INTERVAL_S` until SIGTERM or SIGINT.

    Run one relay at a time; two would publish the same messages twice.
    """
    configure_logging(settings)
    knowledge = build_knowledge(settings)
    is_stopping = threading.Event()

    def stop(signal_number: int, frame: FrameType | None) -> None:
        is_stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    log.info("outbox_relay_started", poll_interval_s=settings.outbox_poll_interval_s)
    try:
        while not is_stopping.is_set():
            relay_pass(knowledge.reconcile_handler, knowledge.publish_handler)
            is_stopping.wait(settings.outbox_poll_interval_s)
    finally:
        knowledge.close()
        log.info("outbox_relay_stopped")


def relay_pass(
    reconcile_handler: ReconcileKnowledgeIngestionsHandler,
    publish_handler: PublishOutboxMessagesHandler,
) -> None:
    """Resend lost messages, then publish every waiting message.

    Reconciling first lets the messages it adds go out in the same pass. When the
    database or the broker is down, the pass stops and the next one tries again;
    nothing is lost, since unpublished messages stay in the outbox.
    """
    command = PublishOutboxMessages()
    try:
        reconcile_handler.reconcile(ReconcileKnowledgeIngestions())
        is_batch_full = True
        while is_batch_full:
            is_batch_full = publish_handler.publish(command) == command.max_messages
    except InfrastructureError as error:
        log.warning("outbox_relay_pass_failed", code=error.code)
