"""Wires ports to adapters. The only place that picks adapters and configures logging."""

import logging
import sys
from dataclasses import dataclass

import pika
import structlog

from offline_rag.knowledge.application.chunk_knowledge_content import (
    ChunkingSizes,
    ChunkKnowledgeContentHandler,
)
from offline_rag.knowledge.application.extract_knowledge_content import (
    ExtractKnowledgeContentHandler,
)
from offline_rag.knowledge.application.fail_knowledge_ingestion import (
    FailKnowledgeIngestionHandler,
)
from offline_rag.knowledge.application.knowledge_ingestion_queries import (
    KnowledgeIngestionQueries,
)
from offline_rag.knowledge.application.ports import IngestionLane
from offline_rag.knowledge.application.publish_knowledge_version import (
    PublishKnowledgeVersionHandler,
)
from offline_rag.knowledge.application.publish_outbox_messages import (
    PublishOutboxMessagesHandler,
)
from offline_rag.knowledge.application.read_pages_with_lvm import ReadPagesWithLvmHandler
from offline_rag.knowledge.application.reconcile_knowledge_ingestions import (
    ReconcileKnowledgeIngestionsHandler,
)
from offline_rag.knowledge.application.reingest_knowledge_item import (
    ReingestKnowledgeItemHandler,
)
from offline_rag.knowledge.application.run_ingestion_step import RunIngestionStepHandler
from offline_rag.knowledge.application.submit_knowledge_item import SubmitKnowledgeItemHandler
from offline_rag.knowledge.domain.duplicate_detection import DuplicateDetector
from offline_rag.knowledge.infrastructure.approximate_tokenizer import ApproximateTokenizer
from offline_rag.knowledge.infrastructure.csv_node_directory import CsvNodeDirectory
from offline_rag.knowledge.infrastructure.docling_document_parser import DoclingDocumentParser
from offline_rag.knowledge.infrastructure.in_process_event_publisher import (
    InProcessEventPublisher,
)
from offline_rag.knowledge.infrastructure.libreoffice_doc_converter import (
    LibreOfficeDocConverter,
)
from offline_rag.knowledge.infrastructure.local_source_file_store import LocalSourceFileStore
from offline_rag.knowledge.infrastructure.model_registry import load_registered_prompt
from offline_rag.knowledge.infrastructure.ollama_client import OllamaClient
from offline_rag.knowledge.infrastructure.ollama_lvm import OllamaLvm
from offline_rag.knowledge.infrastructure.ollama_table_ocr import OllamaTableOcr
from offline_rag.knowledge.infrastructure.pdfium_page_renderer import PdfiumPageRenderer
from offline_rag.knowledge.infrastructure.postgres_database import PostgresDatabase
from offline_rag.knowledge.infrastructure.postgres_duplicate_flag_repository import (
    PostgresDuplicateFlagRepository,
)
from offline_rag.knowledge.infrastructure.postgres_extracted_content_repository import (
    PostgresExtractedContentRepository,
)
from offline_rag.knowledge.infrastructure.postgres_knowledge_chunk_repository import (
    PostgresKnowledgeChunkRepository,
)
from offline_rag.knowledge.infrastructure.postgres_knowledge_ingestion_repository import (
    PostgresKnowledgeIngestionRepository,
)
from offline_rag.knowledge.infrastructure.postgres_knowledge_item_repository import (
    PostgresKnowledgeItemRepository,
)
from offline_rag.knowledge.infrastructure.postgres_outbox import PostgresOutbox
from offline_rag.knowledge.infrastructure.postgres_version_fingerprint_repository import (
    PostgresVersionFingerprintRepository,
)
from offline_rag.knowledge.infrastructure.rabbitmq_ingestion_consumer import (
    RabbitMqIngestionConsumer,
)
from offline_rag.knowledge.infrastructure.rabbitmq_ingestion_message_publisher import (
    RabbitMqIngestionMessagePublisher,
)
from offline_rag.knowledge.infrastructure.rabbitmq_management_queue_monitor import (
    RabbitMqManagementQueueMonitor,
)
from offline_rag.knowledge.infrastructure.system_clock import SystemClock
from offline_rag.knowledge.infrastructure.uuid_id_generator import UuidIdGenerator
from offline_rag.settings import Settings

SOURCE_FILES_DIR_NAME = "source_files"


@dataclass(frozen=True, kw_only=True)
class KnowledgeWiring:
    """The Knowledge Management use cases and queries, and the connections they share."""

    submit_handler: SubmitKnowledgeItemHandler
    publish_version_handler: PublishKnowledgeVersionHandler
    extract_handler: ExtractKnowledgeContentHandler
    read_pages_handler: ReadPagesWithLvmHandler
    chunk_handler: ChunkKnowledgeContentHandler
    reingest_handler: ReingestKnowledgeItemHandler
    fail_handler: FailKnowledgeIngestionHandler
    reconcile_handler: ReconcileKnowledgeIngestionsHandler
    publish_handler: PublishOutboxMessagesHandler
    run_step_handler: RunIngestionStepHandler
    queries: KnowledgeIngestionQueries
    ingestion_repository: PostgresKnowledgeIngestionRepository
    database: PostgresDatabase
    message_publisher: RabbitMqIngestionMessagePublisher

    def close(self) -> None:
        """Close the database pool and the broker connection."""
        self.message_publisher.close()
        self.database.close()


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


def build_knowledge(settings: Settings) -> KnowledgeWiring:
    """Return Knowledge Management on Postgres, local files, local parsers and local models.

    Submitting queues a KnowledgeIngestion; the workers run its steps (ADR 0005).
    Chunk sizes and duplicate thresholds come from `Settings` (ADR 0009, ADR 0010).
    """
    database = PostgresDatabase(
        settings.database_url,
        pool_size=settings.database_pool_size,
        connect_timeout_s=settings.database_connect_timeout_s,
    )
    knowledge_item_repository = PostgresKnowledgeItemRepository(database)
    extracted_content_repository = PostgresExtractedContentRepository(database)
    ingestion_repository = PostgresKnowledgeIngestionRepository(database)
    chunk_repository = PostgresKnowledgeChunkRepository(database)
    fingerprint_repository = PostgresVersionFingerprintRepository(database)
    duplicate_flag_repository = PostgresDuplicateFlagRepository(database)
    detector = DuplicateDetector(
        overlap_chunk_similarity=settings.overlap_chunk_similarity,
        ambiguous_from_similarity=settings.overlap_ambiguous_from_similarity,
        min_chunk_share=settings.overlap_min_chunk_share,
    )
    source_file_store = LocalSourceFileStore(settings.data_dir / SOURCE_FILES_DIR_NAME)
    clock = SystemClock()
    id_generator = UuidIdGenerator()
    event_publisher = InProcessEventPublisher()
    extract_handler = ExtractKnowledgeContentHandler(
        ingestion_repository=ingestion_repository,
        repository=knowledge_item_repository,
        source_file_store=source_file_store,
        parser=DoclingDocumentParser(
            models_dir=settings.docling_models_dir,
            doc_converter=LibreOfficeDocConverter(
                soffice_path=settings.libreoffice_path,
                timeout_s=settings.doc_conversion_timeout_s,
            ),
        ),
        extracted_content_repository=extracted_content_repository,
        clock=clock,
        id_generator=id_generator,
        event_publisher=event_publisher,
        min_page_text_chars=settings.min_page_text_chars,
    )

    model_client = OllamaClient(base_url=settings.ollama_url, timeout_s=settings.model_timeout_s)
    registries = {
        "prompts_dir": settings.prompts_dir,
        "model_manifest_path": settings.model_manifest_path,
    }
    read_pages_handler = ReadPagesWithLvmHandler(
        ingestion_repository=ingestion_repository,
        repository=knowledge_item_repository,
        source_file_store=source_file_store,
        extracted_content_repository=extracted_content_repository,
        page_renderer=PdfiumPageRenderer(dpi=settings.page_render_dpi),
        lvm=OllamaLvm(
            client=model_client,
            prompt=load_registered_prompt(task="page_reading", **registries),
            max_attempts=settings.lvm_max_attempts,
        ),
        table_ocr=OllamaTableOcr(
            client=model_client,
            prompt=load_registered_prompt(task="table_ocr", **registries),
        ),
        clock=clock,
        id_generator=id_generator,
        event_publisher=event_publisher,
        min_page_text_chars=settings.min_page_text_chars,
    )
    chunk_handler = ChunkKnowledgeContentHandler(
        ingestion_repository=ingestion_repository,
        repository=knowledge_item_repository,
        extracted_content_repository=extracted_content_repository,
        chunk_repository=chunk_repository,
        fingerprint_repository=fingerprint_repository,
        duplicate_flag_repository=duplicate_flag_repository,
        tokenizer=ApproximateTokenizer(),
        detector=detector,
        clock=clock,
        event_publisher=event_publisher,
        sizes=ChunkingSizes(
            target_tokens=settings.chunk_target_tokens,
            max_tokens=settings.chunk_max_tokens,
            overlap_share=settings.chunk_overlap_share,
        ),
        words_per_shingle=settings.duplicate_shingle_words,
    )

    node_directory = CsvNodeDirectory(settings.node_registry_path)
    submit_handler = SubmitKnowledgeItemHandler(
        ingestion_repository=ingestion_repository,
        node_directory=node_directory,
        source_file_store=source_file_store,
        fingerprint_repository=fingerprint_repository,
        detector=detector,
        clock=clock,
        id_generator=id_generator,
        event_publisher=event_publisher,
        max_file_mb=settings.max_file_mb,
    )
    fail_handler = FailKnowledgeIngestionHandler(
        ingestion_repository=ingestion_repository, clock=clock
    )
    outbox = PostgresOutbox(database)
    # Connects on the first publish, so commands that publish nothing need no broker.
    message_publisher = RabbitMqIngestionMessagePublisher(settings.rabbitmq_url)
    return KnowledgeWiring(
        submit_handler=submit_handler,
        publish_version_handler=PublishKnowledgeVersionHandler(
            ingestion_repository=ingestion_repository,
            repository=knowledge_item_repository,
            source_file_store=source_file_store,
            fingerprint_repository=fingerprint_repository,
            detector=detector,
            clock=clock,
            id_generator=id_generator,
            event_publisher=event_publisher,
            max_file_mb=settings.max_file_mb,
        ),
        extract_handler=extract_handler,
        read_pages_handler=read_pages_handler,
        chunk_handler=chunk_handler,
        reingest_handler=ReingestKnowledgeItemHandler(
            ingestion_repository=ingestion_repository,
            repository=knowledge_item_repository,
            clock=clock,
            id_generator=id_generator,
        ),
        fail_handler=fail_handler,
        reconcile_handler=ReconcileKnowledgeIngestionsHandler(
            ingestion_repository=ingestion_repository,
            outbox=outbox,
            clock=clock,
            id_generator=id_generator,
            reconcile_after_s=settings.reconcile_after_s,
        ),
        publish_handler=PublishOutboxMessagesHandler(
            outbox=outbox, publisher=message_publisher, clock=clock
        ),
        run_step_handler=RunIngestionStepHandler(
            extract_handler=extract_handler,
            read_pages_handler=read_pages_handler,
            chunk_handler=chunk_handler,
            fail_handler=fail_handler,
            max_attempts=settings.worker_max_attempts,
        ),
        queries=KnowledgeIngestionQueries(
            ingestion_repository=ingestion_repository,
            repository=knowledge_item_repository,
            extracted_content_repository=extracted_content_repository,
            chunk_repository=chunk_repository,
            duplicate_flag_repository=duplicate_flag_repository,
            outbox=outbox,
            node_directory=node_directory,
            queue_monitor=RabbitMqManagementQueueMonitor(
                settings.rabbitmq_management_url,
                virtual_host=pika.URLParameters(settings.rabbitmq_url).virtual_host,
            ),
        ),
        ingestion_repository=ingestion_repository,
        database=database,
        message_publisher=message_publisher,
    )


def build_ingestion_consumer(settings: Settings, lane: IngestionLane) -> RabbitMqIngestionConsumer:
    """Return the broker consumer for the workers of one lane (ADR 0005)."""
    return RabbitMqIngestionConsumer(
        settings.rabbitmq_url,
        lane=lane,
        prefetch_count=settings.worker_prefetch_count,
        retry_delay_s=settings.worker_retry_delay_s,
    )
