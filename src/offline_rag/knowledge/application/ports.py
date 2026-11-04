"""Ports that Knowledge Management use cases depend on. Adapters live in `infrastructure/`."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.extracted_content import ExtractedContent
from offline_rag.knowledge.domain.knowledge_item import KnowledgeItem
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.shared_kernel.domain_event import DomainEvent
from offline_rag.shared_kernel.node_identifier import NodeIdentifier


class KnowledgeItemRepository(Protocol):
    """Stores KnowledgeItems whole, with all their versions."""

    def get_by_id(self, item_id: str) -> KnowledgeItem:
        """Return the item with this id.

        Raises:
            KnowledgeItemNotFoundError: No item has this id.
        """
        ...

    def add(self, item: KnowledgeItem) -> None:
        """Store a new item."""
        ...


class NodeDirectory(Protocol):
    """Reads the Node registry of Organizational Hierarchy."""

    def has_node(self, node_id: NodeIdentifier) -> bool:
        """Return whether a Node with this id is registered."""
        ...


class SourceFileStore(Protocol):
    """Keeps the original files that were submitted (spec §17, file storage)."""

    def save(self, file_name: str, content: bytes) -> str:
        """Store a file and return the reference that finds it again."""
        ...

    def read(self, reference: str) -> bytes:
        """Return the whole file stored under `reference`.

        Raises:
            SourceFileStorageError: The file is missing or cannot be read.
        """
        ...


class DocumentParser(Protocol):
    """Reads DOC, DOCX and PDF files into text, tables and page references (spec §7.3)."""

    def parse(self, content: bytes, document_format: DocumentFormat) -> ExtractedContent:
        """Return the blocks of a file in reading order, with normalized text.

        Pages without a text layer come back without blocks; the LVM reads them.

        Raises:
            DocumentExtractionError: The file cannot be read as its format.
            DocConverterUnavailableError: A DOC file needs LibreOffice, which is missing.
        """
        ...


class ExtractedContentRepository(Protocol):
    """Stores the content extracted from each KnowledgeVersion."""

    def save(self, item_id: str, version_tag: VersionTag, content: ExtractedContent) -> None:
        """Store the content of a version, replacing what was stored for it before."""
        ...

    def get(self, item_id: str, version_tag: VersionTag) -> ExtractedContent:
        """Return the content extracted from a version.

        Raises:
            ExtractedContentNotFoundError: Nothing was extracted from that version yet.
        """
        ...


class Clock(Protocol):
    """Tells the current time."""

    def now(self) -> datetime:
        """Return the current time, timezone-aware."""
        ...


class IdGenerator(Protocol):
    """Creates ids for new aggregates."""

    def new_id(self) -> str:
        """Return an id that has never been returned before."""
        ...


class EventPublisher(Protocol):
    """Hands domain events to the handlers subscribed to them."""

    def publish(self, events: Sequence[DomainEvent]) -> None:
        """Publish the events in order."""
        ...
