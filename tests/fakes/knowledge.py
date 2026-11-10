"""In-memory fakes of the Knowledge Management ports, for unit tests."""

import copy
import math
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from offline_rag.knowledge.application.errors import (
    ExtractedContentNotFoundError,
    IngestionStatusChangedError,
    KnowledgeIngestionNotFoundError,
    KnowledgeItemNotFoundError,
)
from offline_rag.knowledge.application.ports import (
    IngestionQueueDepth,
    KnowledgeIngestionSummary,
    OutboxMessage,
    PageReading,
)
from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.duplicate_detection import DuplicateFlag, VersionFingerprint
from offline_rag.knowledge.domain.extracted_content import ExtractedContent
from offline_rag.knowledge.domain.knowledge_chunk import KnowledgeChunk
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


class InMemoryDuplicateFlagRepository:
    """Keeps flags in a dict by item id and version tag."""

    def __init__(self) -> None:
        self.flags: dict[tuple[str, VersionTag], list[DuplicateFlag]] = {}

    def replace(
        self, item_id: str, version_tag: VersionTag, flags: Sequence[DuplicateFlag]
    ) -> None:
        self.flags[(item_id, version_tag)] = sorted(flags, key=lambda f: f.existing_item_id)

    def list_by_version(self, item_id: str, version_tag: VersionTag) -> list[DuplicateFlag]:
        return list(self.flags.get((item_id, version_tag), []))


class InMemoryKnowledgeIngestionRepository:
    """Keeps copies of ingestions by id, every outbox message in order, and publish times.

    Items and flags given with a new ingestion go into the item and flag
    repositories, as the real adapter writes them in one transaction.
    `InMemoryOutbox` shares the messages.
    A save that expects a status fails for ids in `taken_by_another_worker`, as if
    another worker had started that step first.
    """

    def __init__(
        self,
        item_repository: InMemoryKnowledgeItemRepository,
        flag_repository: InMemoryDuplicateFlagRepository | None = None,
    ) -> None:
        self.item_repository = item_repository
        self.flag_repository = flag_repository or InMemoryDuplicateFlagRepository()
        self.ingestions: dict[str, KnowledgeIngestion] = {}
        self.messages: list[OutboxMessage] = []
        self.published_at: dict[str, datetime] = {}
        self.taken_by_another_worker: set[str] = set()

    def add_with_item(
        self,
        item: KnowledgeItem,
        ingestion: KnowledgeIngestion,
        message: OutboxMessage,
        duplicate_flags: Sequence[DuplicateFlag] = (),
    ) -> None:
        self.item_repository.add(item)
        self.flag_repository.replace(item.item_id, ingestion.version_tag, duplicate_flags)
        self.add(ingestion, message)

    def add_with_version(
        self,
        item: KnowledgeItem,
        ingestion: KnowledgeIngestion,
        message: OutboxMessage,
        duplicate_flags: Sequence[DuplicateFlag] = (),
    ) -> None:
        self.item_repository.add(item)
        self.flag_repository.replace(item.item_id, ingestion.version_tag, duplicate_flags)
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
                ingestion.status
                in {IngestionStatus.QUEUED, IngestionStatus.READING_PAGES, IngestionStatus.CHUNKING}
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

    def find_recent(self, limit: int) -> list[KnowledgeIngestionSummary]:
        recent = sorted(
            self.ingestions.values(),
            key=lambda ingestion: (ingestion.created_at, ingestion.ingestion_id),
            reverse=True,
        )
        summaries = []
        for ingestion in recent[:limit]:
            item = self.item_repository.get_by_id(ingestion.item_id)
            version = item.get_version(ingestion.version_tag)
            summaries.append(
                KnowledgeIngestionSummary(
                    ingestion=copy.deepcopy(ingestion),
                    source_file_name=version.source_file_name,
                    document_format=version.document_format,
                    duplicate_flag_count=len(
                        self.flag_repository.list_by_version(item.item_id, version.version_tag)
                    ),
                )
            )
        return summaries


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

    def count_unpublished(self) -> int:
        return len(self.find_unpublished(len(self.ingestion_repository.messages)))


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

    def list_node_ids(self) -> list[NodeIdentifier]:
        return sorted(self._node_ids, key=lambda node_id: node_id.value)


class FakeIngestionQueueMonitor:
    """Returns the queue depths it was given, or raises the error it was given."""

    def __init__(
        self, depths: list[IngestionQueueDepth] | None = None, error: Exception | None = None
    ) -> None:
        self.depths = depths or []
        self.error = error

    def get_queue_depths(self) -> list[IngestionQueueDepth]:
        if self.error is not None:
            raise self.error
        return list(self.depths)


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


class FakeTokenizer:
    """Counts one token per four characters, rounded up, like the real estimate."""

    def count_tokens(self, text: str) -> int:
        return math.ceil(len(text) / 4)


class InMemoryKnowledgeChunkRepository:
    """Keeps chunks by item id and version tag; reads the active version from the items."""

    def __init__(self, item_repository: InMemoryKnowledgeItemRepository) -> None:
        self.item_repository = item_repository
        self.chunks: dict[tuple[str, VersionTag], list[KnowledgeChunk]] = {}

    def replace(
        self, item_id: str, version_tag: VersionTag, chunks: Sequence[KnowledgeChunk]
    ) -> None:
        self.chunks[(item_id, version_tag)] = list(chunks)

    def list_by_version(self, item_id: str, version_tag: VersionTag) -> list[KnowledgeChunk]:
        return list(self.chunks.get((item_id, version_tag), []))

    def list_active_by_owner(self, owner_node_id: NodeIdentifier) -> list[KnowledgeChunk]:
        return [
            chunk
            for item in sorted(self.item_repository.items.values(), key=lambda i: i.item_id)
            if item.owner_node_id == owner_node_id
            for chunk in self.chunks.get((item.item_id, item.active_version.version_tag), [])
        ]


class InMemoryVersionFingerprintRepository:
    """Builds fingerprints from the stored items, with the text hashes saved here."""

    def __init__(self, item_repository: InMemoryKnowledgeItemRepository) -> None:
        self.item_repository = item_repository
        self.text_hashes: dict[tuple[str, VersionTag], str | None] = {}

    def save_text_hash(
        self, item_id: str, version_tag: VersionTag, normalized_text_hash: str | None
    ) -> None:
        self.text_hashes[(item_id, version_tag)] = normalized_text_hash

    def find_by_content_hash(
        self, owner_node_id: NodeIdentifier, content_hash: str
    ) -> list[VersionFingerprint]:
        return [
            found
            for found in self._all(owner_node_id, active_only=False)
            if found.content_hash == content_hash
        ]

    def find_by_text_hash(
        self, owner_node_id: NodeIdentifier, normalized_text_hash: str
    ) -> list[VersionFingerprint]:
        return [
            found
            for found in self._all(owner_node_id, active_only=False)
            if found.normalized_text_hash == normalized_text_hash
        ]

    def list_active_by_owner(self, owner_node_id: NodeIdentifier) -> list[VersionFingerprint]:
        return self._all(owner_node_id, active_only=True)

    def _all(self, owner_node_id: NodeIdentifier, *, active_only: bool) -> list[VersionFingerprint]:
        return [
            VersionFingerprint(
                item_id=item.item_id,
                version_tag=version.version_tag,
                owner_node_id=item.owner_node_id,
                content_hash=version.content_hash,
                normalized_text_hash=self.text_hashes.get((item.item_id, version.version_tag)),
                metadata=version.metadata,
            )
            for item in sorted(self.item_repository.items.values(), key=lambda i: i.item_id)
            if item.owner_node_id == owner_node_id
            for version in item.versions
            if not active_only or version == item.active_version
        ]
