"""In-memory fakes of the Knowledge Management ports, for unit tests."""

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from offline_rag.knowledge.application.errors import KnowledgeItemNotFoundError
from offline_rag.knowledge.domain.knowledge_item import KnowledgeItem
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
