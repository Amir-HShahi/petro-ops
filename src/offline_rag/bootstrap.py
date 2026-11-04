"""Wires ports to adapters. The only place that picks adapters and configures logging."""

import logging
import sys
from dataclasses import dataclass

import structlog

from offline_rag.knowledge.application.extract_knowledge_content import (
    ExtractKnowledgeContentHandler,
)
from offline_rag.knowledge.application.read_pages_with_lvm import ReadPagesWithLvmHandler
from offline_rag.knowledge.application.submit_knowledge_item import SubmitKnowledgeItemHandler
from offline_rag.knowledge.domain.events import KnowledgeContentExtracted, KnowledgeItemSubmitted
from offline_rag.knowledge.infrastructure.csv_node_directory import CsvNodeDirectory
from offline_rag.knowledge.infrastructure.docx_parser import DocxParser
from offline_rag.knowledge.infrastructure.in_process_event_publisher import (
    InProcessEventPublisher,
)
from offline_rag.knowledge.infrastructure.libreoffice_doc_parser import LibreOfficeDocParser
from offline_rag.knowledge.infrastructure.local_document_parser import LocalDocumentParser
from offline_rag.knowledge.infrastructure.local_source_file_store import LocalSourceFileStore
from offline_rag.knowledge.infrastructure.model_registry import load_registered_prompt
from offline_rag.knowledge.infrastructure.ollama_client import OllamaClient
from offline_rag.knowledge.infrastructure.ollama_lvm import OllamaLvm
from offline_rag.knowledge.infrastructure.ollama_table_ocr import OllamaTableOcr
from offline_rag.knowledge.infrastructure.pdfium_page_renderer import PdfiumPageRenderer
from offline_rag.knowledge.infrastructure.pdfplumber_pdf_parser import PdfplumberPdfParser
from offline_rag.knowledge.infrastructure.sqlite_extracted_content_repository import (
    SqliteExtractedContentRepository,
)
from offline_rag.knowledge.infrastructure.sqlite_knowledge_item_repository import (
    SqliteKnowledgeItemRepository,
)
from offline_rag.knowledge.infrastructure.system_clock import SystemClock
from offline_rag.knowledge.infrastructure.uuid_id_generator import UuidIdGenerator
from offline_rag.settings import Settings

DATABASE_FILE_NAME = "knowledge.sqlite3"
SOURCE_FILES_DIR_NAME = "source_files"


@dataclass(frozen=True, kw_only=True)
class KnowledgeWiring:
    """The Knowledge Management use cases, and the stores entry points read from."""

    submit_handler: SubmitKnowledgeItemHandler
    extract_handler: ExtractKnowledgeContentHandler
    read_pages_handler: ReadPagesWithLvmHandler
    knowledge_item_repository: SqliteKnowledgeItemRepository
    extracted_content_repository: SqliteExtractedContentRepository


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
    """Return Knowledge Management on SQLite, local files, local parsers and local models.

    Every submitted item is extracted right after it is registered, and PDF pages
    without a text layer are then read by the LVM.
    """
    database_path = settings.data_dir / DATABASE_FILE_NAME
    knowledge_item_repository = SqliteKnowledgeItemRepository(database_path)
    extracted_content_repository = SqliteExtractedContentRepository(database_path)
    source_file_store = LocalSourceFileStore(settings.data_dir / SOURCE_FILES_DIR_NAME)
    clock = SystemClock()
    event_publisher = InProcessEventPublisher()
    docx_parser = DocxParser()

    extract_handler = ExtractKnowledgeContentHandler(
        repository=knowledge_item_repository,
        source_file_store=source_file_store,
        parser=LocalDocumentParser(
            docx_parser=docx_parser,
            pdf_parser=PdfplumberPdfParser(),
            doc_parser=LibreOfficeDocParser(
                soffice_path=settings.libreoffice_path,
                timeout_s=settings.doc_conversion_timeout_s,
                docx_parser=docx_parser,
            ),
        ),
        extracted_content_repository=extracted_content_repository,
        clock=clock,
        event_publisher=event_publisher,
        min_page_text_chars=settings.min_page_text_chars,
    )
    event_publisher.subscribe(KnowledgeItemSubmitted, extract_handler.on_knowledge_item_submitted)

    model_client = OllamaClient(base_url=settings.ollama_url, timeout_s=settings.model_timeout_s)
    registries = {
        "prompts_dir": settings.prompts_dir,
        "model_manifest_path": settings.model_manifest_path,
    }
    read_pages_handler = ReadPagesWithLvmHandler(
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
        event_publisher=event_publisher,
        min_page_text_chars=settings.min_page_text_chars,
    )
    event_publisher.subscribe(
        KnowledgeContentExtracted, read_pages_handler.on_knowledge_content_extracted
    )

    submit_handler = SubmitKnowledgeItemHandler(
        repository=knowledge_item_repository,
        node_directory=CsvNodeDirectory(settings.node_registry_path),
        source_file_store=source_file_store,
        clock=clock,
        id_generator=UuidIdGenerator(),
        event_publisher=event_publisher,
    )
    return KnowledgeWiring(
        submit_handler=submit_handler,
        extract_handler=extract_handler,
        read_pages_handler=read_pages_handler,
        knowledge_item_repository=knowledge_item_repository,
        extracted_content_repository=extracted_content_repository,
    )
