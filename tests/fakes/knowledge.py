"""In-memory fakes of the Knowledge Management ports, for unit tests."""

import copy
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from offline_rag.knowledge.application.errors import (
    ExtractedContentNotFoundError,
    IngestionStatusChangedError,
    KnowledgeIngestionNotFoundError,
    KnowledgeItemNotFoundError,
)
from offline_rag.knowledge.application.ports import OutboxMessage, PageReading
from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.extracted_content import ExtractedContent
from offline_rag.knowledge.domain.knowledge_ingestion import IngestionStatus, KnowledgeIngestion
from offline_rag.knowledge.domain.knowledge_item import KnowledgeItem
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.knowledge.infrastructure.errors import SourceFileStorageError
from offline_rag.shared_kernel.domain_event import DomainEvent
from offline_rag.shared_kernel.node_identifier import NodeIdentifier


class InMemoryKnowledgeItemRepository:
    """Keeps items in a dict by id."""

    def __init__(self) -> None:
        self.items: dict[str, KnowledgeItem] = {}

    def get_by_id(self, item_id: str) -> KnowledgeItem:
        try:
            return self.items[item_id]
        except KeyError as error:
            raise KnowledgeItemNotFoundError(item_id) from error

    def add(self, item: KnowledgeItem) -> None:
        self.items[item.item_id] = item


class InMemoryKnowledgeIngestionRepository:
    """Keeps copies of ingestions by id, every outbox message in order, and publish times.

    Items given with a new ingestion go into the item repository, as the real
    adapter writes both in one transaction. `InMemoryOutbox` shares the messages.
    A save that expects a status fails for ids in `taken_by_another_worker`, as if
    another worker had started that step first.
    """

    def __init__(self, item_repository: InMemoryKnowledgeItemRepository) -> None:
        self.item_repository = item_repository
        self.ingestions: dict[str, KnowledgeIngestion] = {}
        self.messages: list[OutboxMessage] = []
        self.published_at: dict[str, datetime] = {}
        self.taken_by_another_worker: set[str] = set()

    def add_with_item(
        self, item: KnowledgeItem, ingestion: KnowledgeIngestion, message: OutboxMessage
    ) -> None:
        self.item_repository.add(item)
        self.add(ingestion, message)

    def add(self, ingestion: KnowledgeIngestion, message: OutboxMessage) -> None:
        self.save(ingestion, message)

    def save(
        self,
        ingestion: KnowledgeIngestion,
        message: OutboxMessage | None = None,
        *,
        expected_status: IngestionStatus | None = None,
    ) -> None:
        stored = self.ingestions.get(ingestion.ingestion_id)
        if expected_status is not None and (
            ingestion.ingestion_id in self.taken_by_another_worker
            or stored is None
            or stored.status != expected_status
        ):
            raise IngestionStatusChangedError(
                ingestion.ingestion_id, expected_status=expected_status.value
            )
        # A copy, so a test sees what was saved, not later changes to the object.
        self.ingestions[ingestion.ingestion_id] = copy.deepcopy(ingestion)
        if message is not None:
            self.messages.append(message)

    def get_by_id(self, ingestion_id: str) -> KnowledgeIngestion:
        try:
            return copy.deepcopy(self.ingestions[ingestion_id])
        except KeyError as error:
            raise KnowledgeIngestionNotFoundError(ingestion_id) from error

    def find_running(self, item_id: str, version_tag: VersionTag) -> KnowledgeIngestion | None:
        return next(
            (
                copy.deepcopy(ingestion)
                for ingestion in self.ingestions.values()
                if ingestion.item_id == item_id
                and ingestion.version_tag == version_tag
                and ingestion.is_running
            ),
            None,
        )

    def find_stalled(self, stalled_since: datetime, limit: int) -> list[KnowledgeIngestion]:
        def is_stalled(ingestion: KnowledgeIngestion) -> bool:
            return (
                ingestion.status in {IngestionStatus.QUEUED, IngestionStatus.READING_PAGES}
                and ingestion.updated_at < stalled_since
                and all(
                    message.outbox_id in self.published_at and message.created_at < stalled_since
                    for message in self.messages
                    if message.ingestion_id == ingestion.ingestion_id
                )
            )

        stalled = sorted(
            filter(is_stalled, self.ingestions.values()),
            key=lambda ingestion: (ingestion.updated_at, ingestion.ingestion_id),
        )
        return [copy.deepcopy(ingestion) for ingestion in stalled[:limit]]


class InMemoryOutbox:
    """Reads and writes the messages of an `InMemoryKnowledgeIngestionRepository`."""

    def __init__(self, ingestion_repository: InMemoryKnowledgeIngestionRepository) -> None:
        self.ingestion_repository = ingestion_repository

    def find_unpublished(self, limit: int) -> list[OutboxMessage]:
        unpublished = [
            message
            for message in self.ingestion_repository.messages
            if message.outbox_id not in self.ingestion_repository.published_at
        ]
        return sorted(unpublished, key=lambda message: message.created_at)[:limit]

    def mark_published(self, outbox_id: str, published_at: datetime) -> None:
        self.ingestion_repository.published_at.setdefault(outbox_id, published_at)

    def add(self, message: OutboxMessage) -> None:
        self.ingestion_repository.messages.append(message)


class FakeIngestionMessagePublisher:
    """Records published messages, and raises the error it was given from call `fail_from` on."""

    def __init__(self, error: Exception | None = None, fail_from: int = 1) -> None:
        self._error = error
        self._fail_from = fail_from
        self.calls = 0
        self.published: list[OutboxMessage] = []

    def publish(self, message: OutboxMessage) -> None:
        self.calls += 1
        if self._error is not None and self.calls >= self._fail_from:
            raise self._error
        self.published.append(message)


class FakeNodeDirectory:
    """Knows only the Node ids it was given."""

    def __init__(self, node_ids: Iterable[str]) -> None:
        self._node_ids = {NodeIdentifier(node_id) for node_id in node_ids}

    def has_node(self, node_id: NodeIdentifier) -> bool:
        return node_id in self._node_ids


class InMemorySourceFileStore:
    """Keeps files in a dict under references `file-1`, `file-2`, ..."""

    def __init__(self) -> None:
        self.files: dict[str, tuple[str, bytes]] = {}

    def save(self, file_name: str, content: bytes) -> str:
        reference = f"file-{len(self.files) + 1}"
        self.files[reference] = (file_name, content)
        return reference

    def read(self, reference: str) -> bytes:
        try:
            return self.files[reference][1]
        except KeyError as error:
            raise SourceFileStorageError(reference) from error


class FakeDocumentParser:
    """Returns the content it was given, or raises the error it was given, and records calls."""

    def __init__(
        self, content: ExtractedContent | None = None, error: Exception | None = None
    ) -> None:
        self._content = content
        self._error = error
        self.calls: list[tuple[bytes, DocumentFormat]] = []

    def parse(self, content: bytes, document_format: DocumentFormat) -> ExtractedContent:
        self.calls.append((content, document_format))
        if self._error is not None:
            raise self._error
        assert self._content is not None
        return self._content


class InMemoryExtractedContentRepository:
    """Keeps extracted content in a dict by item id and version tag."""

    def __init__(self) -> None:
        self.contents: dict[tuple[str, VersionTag], ExtractedContent] = {}

    def save(self, item_id: str, version_tag: VersionTag, content: ExtractedContent) -> None:
        self.contents[(item_id, version_tag)] = content

    def get(self, item_id: str, version_tag: VersionTag) -> ExtractedContent:
        try:
            return self.contents[(item_id, version_tag)]
        except KeyError as error:
            raise ExtractedContentNotFoundError(item_id, version_tag.value) from error


class FakeClock:
    """Always returns the same time."""

    def __init__(self, now: datetime = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class FakeIdGenerator:
    """Returns `ki-1`, `ki-2`, ... in order."""

    def __init__(self, prefix: str = "ki") -> None:
        self._prefix = prefix
        self._count = 0

    def new_id(self) -> str:
        self._count += 1
        return f"{self._prefix}-{self._count}"


class InMemoryEventPublisher:
    """Records every published event in order."""

    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    def publish(self, events: Sequence[DomainEvent]) -> None:
        self.events.extend(events)


class FakePageRenderer:
    """Returns a fake image naming the page, and records which pages were drawn."""

    def __init__(self) -> None:
        self.pages: list[int] = []

    def render(self, pdf: bytes, page_number: int) -> bytes:
        self.pages.append(page_number)
        return f"image of page {page_number}".encode()


class FakeLvm:
    """Returns the reading set for each page image, or raises the error it was given.

    Every call is appended to `calls`, which a test may share with `FakeTableOcr`
    to check the order the two models were used in.
    """

    def __init__(
        self,
        readings: dict[int, PageReading] | None = None,
        error: Exception | None = None,
        calls: list[str] | None = None,
    ) -> None:
        self._readings = readings or {}
        self._error = error
        self.calls = [] if calls is None else calls

    def read_page(self, image_png: bytes) -> PageReading:
        page_number = int(image_png.decode().rsplit(" ", 1)[1])
        self.calls.append(f"lvm reads page {page_number}")
        if self._error is not None:
            raise self._error
        return self._readings.get(page_number, PageReading(items=()))

    def release(self) -> None:
        self.calls.append("lvm released")


class FakeTableOcr:
    """Returns the tables set for each page image, and records every call in `calls`."""

    def __init__(
        self,
        tables: dict[int, list[list[list[str]]]] | None = None,
        calls: list[str] | None = None,
    ) -> None:
        self._tables = tables or {}
        self.calls = [] if calls is None else calls

    @property
    def pages(self) -> list[int]:
        return [int(call.rsplit(" ", 1)[1]) for call in self.calls if call.startswith("ocr reads")]

    def read_tables(self, image_png: bytes) -> list[list[list[str]]]:
        page_number = int(image_png.decode().rsplit(" ", 1)[1])
        self.calls.append(f"ocr reads page {page_number}")
        return self._tables.get(page_number, [])

    def release(self) -> None:
        self.calls.append("ocr released")
