"""Use case: register a source file as a new KnowledgeItem and queue its ingestion.

Spec §7.2 steps 1 and 2; the later steps run in the workers (ADR 0005).
"""

import structlog

from offline_rag.knowledge.application.commands import SubmitKnowledgeItem
from offline_rag.knowledge.application.duplicate_checks import (
    duplicate_detected_events,
    find_exact_duplicates,
    fingerprint_of,
)
from offline_rag.knowledge.application.errors import (
    OwnerNodeNotFoundError,
    SourceFileTooLargeError,
)
from offline_rag.knowledge.application.ingestion_queueing import (
    IngestionReceipt,
    queue_ingestion,
    receipt_for,
)
from offline_rag.knowledge.application.ports import (
    Clock,
    EventPublisher,
    IdGenerator,
    KnowledgeIngestionRepository,
    NodeDirectory,
    SourceFileStore,
    VersionFingerprintRepository,
)
from offline_rag.knowledge.domain.document_format import detect_document_format
from offline_rag.knowledge.domain.duplicate_detection import DuplicateDetector
from offline_rag.knowledge.domain.knowledge_item import KnowledgeItem
from offline_rag.knowledge.domain.knowledge_version import compute_content_hash

log = structlog.get_logger()

BYTES_PER_MB = 1024 * 1024


class SubmitKnowledgeItemHandler:
    """Registers a file as a KnowledgeItem with its first version, and queues its ingestion.

    A file that is byte for byte another item of the same Node is flagged as an
    exact duplicate here, and still registered (ADR 0010). The other duplicate
    checks need the text, so they run in the chunking step.
    """

    def __init__(
        self,
        *,
        ingestion_repository: KnowledgeIngestionRepository,
        node_directory: NodeDirectory,
        source_file_store: SourceFileStore,
        fingerprint_repository: VersionFingerprintRepository,
        detector: DuplicateDetector,
        clock: Clock,
        id_generator: IdGenerator,
        event_publisher: EventPublisher,
        max_file_mb: int,
    ) -> None:
        """Create the handler with the ports it needs.

        Args:
            max_file_mb: The largest file accepted, in megabytes of 1,048,576 bytes.
        """
        self._ingestion_repository = ingestion_repository
        self._node_directory = node_directory
        self._source_file_store = source_file_store
        self._fingerprint_repository = fingerprint_repository
        self._detector = detector
        self._clock = clock
        self._id_generator = id_generator
        self._event_publisher = event_publisher
        self._max_file_mb = max_file_mb

    def submit(self, command: SubmitKnowledgeItem) -> IngestionReceipt:
        """Register the file and return the queued ingestion.

        The file is checked before anything is stored, so a rejected file leaves
        no trace. The item, its ingestion and the message that starts it are
        stored together with any exact duplicate flag, so the run cannot be lost
        between them.

        Raises:
            SourceFileTooLargeError: The file is larger than `max_file_mb`.
            OwnerNodeNotFoundError: The owner Node is not registered.
            EmptySourceFileError: The file has no content.
            UnsupportedDocumentFormatError: The file is not DOC, DOCX or PDF.
        """
        if len(command.content) > self._max_file_mb * BYTES_PER_MB:
            raise SourceFileTooLargeError(
                file_name=command.source_file_name, max_file_mb=self._max_file_mb
            )
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
        ingestion, message = queue_ingestion(
            item_id=item.item_id,
            version_tag=item.active_version.version_tag,
            request_id=command.request_id,
            clock=self._clock,
            id_generator=self._id_generator,
        )
        flags = find_exact_duplicates(
            fingerprint_of(item, item.active_version),
            fingerprints=self._fingerprint_repository,
            detector=self._detector,
        )
        self._ingestion_repository.add_with_item(item, ingestion, message, flags)
        self._event_publisher.publish(
            [
                *item.pull_events(),
                *duplicate_detected_events(flags, occurred_at=self._clock.now()),
            ]
        )
        log.info(
            "knowledge_item_submitted",
            item_id=item.item_id,
            ingestion_id=ingestion.ingestion_id,
            node_id=command.owner_node_id.value,
            version_tag=item.active_version.version_tag.value,
            document_format=document_format.value,
            size_bytes=len(command.content),
            duplicate_flags=[flag.kind.value for flag in flags],
        )
        return receipt_for(ingestion)
