"""Use case: extract the text and structure of a KnowledgeVersion (spec §7.2 steps 3 and 4).

The text worker runs it for every queued KnowledgeIngestion (ADR 0005).
"""

import structlog

from offline_rag.knowledge.application.commands import ExtractKnowledgeContent
from offline_rag.knowledge.application.errors import IngestionStatusChangedError
from offline_rag.knowledge.application.ingestion_queueing import next_step_message
from offline_rag.knowledge.application.ports import (
    Clock,
    DocumentParser,
    EventPublisher,
    ExtractedContentRepository,
    IdGenerator,
    IngestionLane,
    KnowledgeIngestionRepository,
    KnowledgeItemRepository,
    SourceFileStore,
)
from offline_rag.knowledge.domain.events import KnowledgeContentExtracted
from offline_rag.knowledge.domain.extracted_content import ContentBlockKind, ExtractedContent
from offline_rag.knowledge.domain.knowledge_ingestion import IngestionStatus, KnowledgeIngestion
from offline_rag.shared_kernel.errors import InfrastructureError, ProjectError

log = structlog.get_logger()


class ExtractKnowledgeContentHandler:
    """Reads the stored file of a version, parses it and stores the blocks.

    PDF pages without a text layer are handed to the vision worker; otherwise the
    ingestion is completed here.
    """

    def __init__(
        self,
        *,
        ingestion_repository: KnowledgeIngestionRepository,
        repository: KnowledgeItemRepository,
        source_file_store: SourceFileStore,
        parser: DocumentParser,
        extracted_content_repository: ExtractedContentRepository,
        clock: Clock,
        id_generator: IdGenerator,
        event_publisher: EventPublisher,
        min_page_text_chars: int,
    ) -> None:
        """Create the handler.

        Args:
            ingestion_repository: Where KnowledgeIngestions and their messages are stored.
            repository: Where KnowledgeItems are stored.
            source_file_store: Where the original files are kept.
            parser: Reads DOC, DOCX and PDF files.
            extracted_content_repository: Where the extracted blocks go.
            clock: Stamps the ingestion and the event.
            id_generator: Names the message for the vision worker.
            event_publisher: Receives `KnowledgeContentExtracted`.
            min_page_text_chars: A PDF page with fewer non-space characters than
                this has no usable text layer and is left for the LVM.
        """
        self._ingestion_repository = ingestion_repository
        self._repository = repository
        self._source_file_store = source_file_store
        self._parser = parser
        self._extracted_content_repository = extracted_content_repository
        self._clock = clock
        self._id_generator = id_generator
        self._event_publisher = event_publisher
        self._min_page_text_chars = min_page_text_chars

    @property
    def min_page_text_chars(self) -> int:
        """The character count below which a PDF page counts as having no text layer."""
        return self._min_page_text_chars

    def extract(self, command: ExtractKnowledgeContent) -> KnowledgeIngestion:
        """Extract the version of an ingestion and return the ingestion in its new state.

        A message seen again after this step has committed changes nothing, and
        when two workers get the same run only the first one extracts. An error
        that a retry cannot fix, such as a damaged file, ends the ingestion as
        FAILED instead of being raised.

        Raises:
            KnowledgeIngestionNotFoundError: The ingestion does not exist.
            InfrastructureError: A store, the parser's converter or the database
                failed; the step can be retried.
        """
        ingestion = self._ingestion_repository.get_by_id(command.ingestion_id)
        status_before = ingestion.status
        can_start = status_before == IngestionStatus.QUEUED or (
            status_before == IngestionStatus.EXTRACTING and command.is_redelivery
        )
        if not can_start:
            log.info(
                "knowledge_extraction_skipped",
                ingestion_id=ingestion.ingestion_id,
                status=status_before.value,
            )
            return ingestion

        ingestion.start_extraction(self._clock.now())
        try:
            self._ingestion_repository.save(ingestion, expected_status=status_before)
        except IngestionStatusChangedError:
            log.info("knowledge_extraction_taken", ingestion_id=ingestion.ingestion_id)
            return self._ingestion_repository.get_by_id(ingestion.ingestion_id)
        try:
            content = self._extract_content(ingestion)
        except InfrastructureError:
            raise
        except ProjectError as error:
            ingestion.fail(
                failure_code=error.code, failure_detail=str(error), now=self._clock.now()
            )
            self._ingestion_repository.save(ingestion)
            log.warning(
                "knowledge_extraction_failed",
                ingestion_id=ingestion.ingestion_id,
                item_id=ingestion.item_id,
                code=error.code,
            )
            return ingestion

        pages_without_text = content.pages_without_text(
            min_page_text_chars=self._min_page_text_chars
        )
        if pages_without_text:
            ingestion.wait_for_page_reading(self._clock.now())
            self._ingestion_repository.save(
                ingestion,
                next_step_message(
                    ingestion,
                    IngestionLane.VISION,
                    clock=self._clock,
                    id_generator=self._id_generator,
                ),
            )
        else:
            ingestion.complete(
                blocks_for_review=sum(block.needs_human_review for block in content.blocks),
                now=self._clock.now(),
            )
            self._ingestion_repository.save(ingestion)

        self._event_publisher.publish(
            [
                KnowledgeContentExtracted(
                    occurred_at=self._clock.now(),
                    item_id=ingestion.item_id,
                    version_tag=ingestion.version_tag,
                    block_count=len(content.blocks),
                    pages_without_text=pages_without_text,
                )
            ]
        )
        log.info(
            "knowledge_content_extracted",
            ingestion_id=ingestion.ingestion_id,
            item_id=ingestion.item_id,
            version_tag=ingestion.version_tag.value,
            document_format=content.document_format.value,
            block_count=len(content.blocks),
            table_count=sum(block.kind == ContentBlockKind.TABLE for block in content.blocks),
            page_count=content.page_count,
            pages_without_text=list(pages_without_text),
        )
        return ingestion

    def _extract_content(self, ingestion: KnowledgeIngestion) -> ExtractedContent:
        item = self._repository.get_by_id(ingestion.item_id)
        version = item.get_version(ingestion.version_tag)
        file_content = self._source_file_store.read(version.source_file_reference)
        content = self._parser.parse(file_content, version.document_format)
        self._extracted_content_repository.save(item.item_id, version.version_tag, content)
        return content
