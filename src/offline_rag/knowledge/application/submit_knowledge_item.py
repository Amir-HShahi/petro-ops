"""Use case: register a source file as a new KnowledgeItem (spec §7.2 steps 1 and 2)."""

import structlog

from offline_rag.knowledge.application.commands import SubmitKnowledgeItem
from offline_rag.knowledge.application.errors import OwnerNodeNotFoundError
from offline_rag.knowledge.application.ports import (
    Clock,
    EventPublisher,
    IdGenerator,
    KnowledgeItemRepository,
    NodeDirectory,
    SourceFileStore,
)
from offline_rag.knowledge.domain.document_format import detect_document_format
from offline_rag.knowledge.domain.knowledge_item import KnowledgeItem
from offline_rag.knowledge.domain.knowledge_version import compute_content_hash

log = structlog.get_logger()


class SubmitKnowledgeItemHandler:
    """Registers a file as a KnowledgeItem with its first version.

    Duplicate detection (phase 5) and text extraction run after this step. The
    content hash recorded here is what the exact duplicate check compares.
    """

    def __init__(
        self,
        *,
        repository: KnowledgeItemRepository,
        node_directory: NodeDirectory,
        source_file_store: SourceFileStore,
        clock: Clock,
        id_generator: IdGenerator,
        event_publisher: EventPublisher,
    ) -> None:
        """Create the handler with the ports it needs."""
        self._repository = repository
        self._node_directory = node_directory
        self._source_file_store = source_file_store
        self._clock = clock
        self._id_generator = id_generator
        self._event_publisher = event_publisher

    def submit(self, command: SubmitKnowledgeItem) -> str:
        """Register the file and return the id of the new KnowledgeItem.

        The file is checked before anything is stored, so a rejected file leaves
        no trace.

        Raises:
            OwnerNodeNotFoundError: The owner Node is not registered.
            EmptySourceFileError: The file has no content.
            UnsupportedDocumentFormatError: The file is not DOC, DOCX or PDF.
        """
        if not self._node_directory.has_node(command.owner_node_id):
            raise OwnerNodeNotFoundError(command.owner_node_id)
        document_format = detect_document_format(
            command.content, file_name=command.source_file_name
        )

        source_file_reference = self._source_file_store.save(
            command.source_file_name, command.content
        )
        item = KnowledgeItem.submit(
            item_id=self._id_generator.new_id(),
            owner_node_id=command.owner_node_id,
            scope=command.scope,
            metadata=command.metadata,
            source_file_name=command.source_file_name,
            source_file_reference=source_file_reference,
            document_format=document_format,
            content_hash=compute_content_hash(command.content),
            submitted_at=self._clock.now(),
        )
        self._repository.add(item)
        self._event_publisher.publish(item.pull_events())
        log.info(
            "knowledge_item_submitted",
            item_id=item.item_id,
            node_id=command.owner_node_id.value,
            version_tag=item.active_version.version_tag.value,
            document_format=document_format.value,
            size_bytes=len(command.content),
        )
        return item.item_id
