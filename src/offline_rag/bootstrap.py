"""Wires ports to adapters. The only place that picks adapters and configures logging."""

import logging
import sys

import structlog

from offline_rag.knowledge.application.submit_knowledge_item import SubmitKnowledgeItemHandler
from offline_rag.knowledge.infrastructure.csv_node_directory import CsvNodeDirectory
from offline_rag.knowledge.infrastructure.in_process_event_publisher import (
    InProcessEventPublisher,
)
from offline_rag.knowledge.infrastructure.local_source_file_store import LocalSourceFileStore
from offline_rag.knowledge.infrastructure.sqlite_knowledge_item_repository import (
    SqliteKnowledgeItemRepository,
)
from offline_rag.knowledge.infrastructure.system_clock import SystemClock
from offline_rag.knowledge.infrastructure.uuid_id_generator import UuidIdGenerator
from offline_rag.settings import Settings

DATABASE_FILE_NAME = "knowledge.sqlite3"
SOURCE_FILES_DIR_NAME = "source_files"


def configure_logging(settings: Settings) -> None:
    """Write JSON log lines to stderr, so stdout stays free for command output."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[settings.log_level.upper()]
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=False,
    )


def build_submit_knowledge_item_handler(settings: Settings) -> SubmitKnowledgeItemHandler:
    """Return the Register use case backed by SQLite, local files and the CSV Node registry."""
    return SubmitKnowledgeItemHandler(
        repository=SqliteKnowledgeItemRepository(settings.data_dir / DATABASE_FILE_NAME),
        node_directory=CsvNodeDirectory(settings.node_registry_path),
        source_file_store=LocalSourceFileStore(settings.data_dir / SOURCE_FILES_DIR_NAME),
        clock=SystemClock(),
        id_generator=UuidIdGenerator(),
        event_publisher=InProcessEventPublisher(),
    )
