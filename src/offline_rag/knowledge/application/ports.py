"""Ports that Knowledge Management use cases depend on. Adapters live in `infrastructure/`."""

from collections.abc import Sequence
from dataclasses import dataclass
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


@dataclass(frozen=True, kw_only=True)
class PageTable:
    """One table as the LVM read it from a page image.

    Attributes:
        header: The header row.
        rows: The data rows.
        row_labels: The first cell of each data row, read a second time on its own.
    """

    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    row_labels: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class PageReading:
    """What the LVM read from one page image, in reading order.

    Attributes:
        items: Each paragraph as text and each table as a `PageTable`, in the
            order they stand on the page.
    """

    items: tuple[str | PageTable, ...]

    @property
    def tables(self) -> tuple[PageTable, ...]:
        """The tables on the page, top to bottom."""
        return tuple(item for item in self.items if isinstance(item, PageTable))


class PageRenderer(Protocol):
    """Draws a PDF page as an image for the vision models."""

    def render(self, pdf: bytes, page_number: int) -> bytes:
        """Return the page, starting at 1, as a PNG image.

        Raises:
            DocumentExtractionError: The file is not a readable PDF or has no such page.
        """
        ...


class LVM(Protocol):
    """A local vision model that reads text and tables from a page image (ADR 0002)."""

    def read_page(self, image_png: bytes) -> PageReading:
        """Return what is printed on the page.

        Raises:
            ModelUnavailableError: The local model server cannot be reached or failed.
            ModelOutputInvalidError: The model kept answering in the wrong shape.
        """
        ...

    def release(self) -> None:
        """Free the memory the model holds. It loads again on its next use.

        Only one large model fits next to the rest of the system on a 16 GB
        machine, so each model is released when its pass is done (ADR 0002).
        """
        ...


class TableOcr(Protocol):
    """A local OCR model that reads only the tables of a page image (ADR 0002)."""

    def read_tables(self, image_png: bytes) -> list[list[list[str]]]:
        """Return every table on the page as rows of cells, header row first.

        Raises:
            ModelUnavailableError: The local model server cannot be reached or failed.
        """
        ...

    def release(self) -> None:
        """Free the memory the model holds. It loads again on its next use."""
        ...
