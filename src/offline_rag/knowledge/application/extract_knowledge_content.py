"""Use case: extract the text and structure of a KnowledgeVersion (spec §7.2 steps 3 and 4)."""

import structlog

from offline_rag.knowledge.application.commands import ExtractKnowledgeContent
from offline_rag.knowledge.application.ports import (
    Clock,
    DocumentParser,
    EventPublisher,
    ExtractedContentRepository,
    KnowledgeItemRepository,
    SourceFileStore,
)
from offline_rag.knowledge.domain.events import KnowledgeContentExtracted, KnowledgeItemSubmitted
from offline_rag.knowledge.domain.extracted_content import ContentBlockKind, ExtractedContent
from offline_rag.shared_kernel.domain_event import DomainEvent
from offline_rag.shared_kernel.errors import ProjectError

log = structlog.get_logger()


class ExtractKnowledgeContentHandler:
    """Reads the stored file of a version, parses it and stores the blocks.

    It runs on its own for every new KnowledgeItem (`on_knowledge_item_submitted`)
    and can be run again for any version, for example after a parser fix.
    """

    def __init__(
        self,
        *,
        repository: KnowledgeItemRepository,
        source_file_store: SourceFileStore,
        parser: DocumentParser,
        extracted_content_repository: ExtractedContentRepository,
        clock: Clock,
        event_publisher: EventPublisher,
        min_page_text_chars: int,
    ) -> None:
        """Create the handler.

        Args:
            repository: Where KnowledgeItems are stored.
            source_file_store: Where the original files are kept.
            parser: Reads DOC, DOCX and PDF files.
            extracted_content_repository: Where the extracted blocks go.
            clock: Stamps the event.
            event_publisher: Receives `KnowledgeContentExtracted`.
            min_page_text_chars: A PDF page with fewer non-space characters than
                this has no usable text layer and is left for the LVM.
        """
        self._repository = repository
        self._source_file_store = source_file_store
        self._parser = parser
        self._extracted_content_repository = extracted_content_repository
        self._clock = clock
        self._event_publisher = event_publisher
        self._min_page_text_chars = min_page_text_chars

    @property
    def min_page_text_chars(self) -> int:
        """The character count below which a PDF page counts as having no text layer."""
        return self._min_page_text_chars

    def extract(self, command: ExtractKnowledgeContent) -> ExtractedContent:
        """Extract one version and return its content.

        Raises:
            KnowledgeItemNotFoundError: The item does not exist.
            KnowledgeVersionNotFoundError: The item has no such version.
            SourceFileStorageError: The stored file cannot be read.
            DocumentExtractionError: The file cannot be read as its format.
            DocConverterUnavailableError: A DOC file needs LibreOffice, which is missing.
        """
        item = self._repository.get_by_id(command.item_id)
        version = item.get_version(command.version_tag)
        file_content = self._source_file_store.read(version.source_file_reference)

        content = self._parser.parse(file_content, version.document_format)
        self._extracted_content_repository.save(item.item_id, version.version_tag, content)

        pages_without_text = content.pages_without_text(
            min_page_text_chars=self._min_page_text_chars
        )
        self._event_publisher.publish(
            [
                KnowledgeContentExtracted(
                    occurred_at=self._clock.now(),
                    item_id=item.item_id,
                    version_tag=version.version_tag,
                    block_count=len(content.blocks),
                    pages_without_text=pages_without_text,
                )
            ]
        )
        log.info(
            "knowledge_content_extracted",
            item_id=item.item_id,
            version_tag=version.version_tag.value,
            document_format=version.document_format.value,
            block_count=len(content.blocks),
            table_count=sum(block.kind == ContentBlockKind.TABLE for block in content.blocks),
            page_count=content.page_count,
            pages_without_text=list(pages_without_text),
        )
        return content

    def on_knowledge_item_submitted(self, event: DomainEvent) -> None:
        """Extract the first version of a newly submitted item.

        A failed extraction does not undo the registration: the item stays, the
        failure is logged, and `extract` can be run for it later.
        """
        if not isinstance(event, KnowledgeItemSubmitted):
            return
        try:
            self.extract(
                ExtractKnowledgeContent(item_id=event.item_id, version_tag=event.version_tag)
            )
        except ProjectError as error:
            log.warning(
                "knowledge_content_extraction_failed",
                item_id=event.item_id,
                version_tag=event.version_tag.value,
                code=error.code,
            )
