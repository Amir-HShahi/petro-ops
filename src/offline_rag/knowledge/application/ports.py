"""Ports that Knowledge Management use cases depend on. Adapters live in `infrastructure/`."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from offline_rag.knowledge.domain.knowledge_item import KnowledgeItem
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
