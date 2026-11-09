"""Ports of Organizational Hierarchy: what its use cases need from the outside."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from offline_rag.organization.domain.layer import Layer
from offline_rag.organization.domain.node import Node
from offline_rag.shared_kernel.domain_event import DomainEvent
from offline_rag.shared_kernel.layer_index import LayerIndex
from offline_rag.shared_kernel.node_identifier import NodeIdentifier


class NodeRepository(Protocol):
    """Stores Nodes (docs/domain-model.md, section 11)."""

    def get_by_id(self, node_id: NodeIdentifier) -> Node:
        """Return the Node with this id.

        Raises:
            NodeNotFoundError: No Node has this id.
        """
        ...

    def find_by_id(self, node_id: NodeIdentifier) -> Node | None:
        """Return the Node with this id, or None if it is not registered."""
        ...

    def find_all(self) -> list[Node]:
        """Return every Node, from the top Layer down, then by id."""
        ...

    def add(self, node: Node) -> None:
        """Store a new Node."""
        ...


class LayerRepository(Protocol):
    """Stores the five Layers. They exist from the start, so there is no `add`."""

    def get_by_index(self, layer_index: LayerIndex) -> Layer:
        """Return the Layer at this index.

        Raises:
            LayerNotFoundError: The Layer is not in the registry.
        """
        ...

    def find_all(self) -> list[Layer]:
        """Return every Layer, from Layer 0 down."""
        ...


class Clock(Protocol):
    """Tells the current time."""

    def now(self) -> datetime:
        """Return the current time, timezone-aware."""
        ...


class EventPublisher(Protocol):
    """Hands domain events to whoever reacts to them."""

    def publish(self, events: Sequence[DomainEvent]) -> None:
        """Publish the events in order."""
        ...
