"""The Node aggregate root."""

from datetime import datetime

from offline_rag.organization.domain.errors import (
    ParentNodeNotInHigherLayerError,
    ParentNodeRequiredError,
    ParentStructureNotTrackedError,
    TopLayerNodeHasParentError,
)
from offline_rag.organization.domain.events import NodeRegistered
from offline_rag.shared_kernel.confidentiality_level import ConfidentialityLevel
from offline_rag.shared_kernel.domain_event import DomainEvent
from offline_rag.shared_kernel.layer_index import LayerIndex
from offline_rag.shared_kernel.node_identifier import NodeIdentifier


class Node:
    """A company, organization, unit, project or team in one Layer (spec §5.2, §6.1).

    Invariants:
    - The `NodeIdentifier` never changes (spec §5.3).
    - The Node belongs to exactly one Layer.
    - Only a Layer 0 Node has no parent.
    - A parent is in a higher Layer (a lower index). It may skip Layers, so the
      parent chain has no cycle (registry README).
    - A Node gets children only when its internal structure is tracked; otherwise its
      inside is outside the system boundary (spec §6.1).

    The parent's Layer and tracking flag are checked by `register`, which sees the
    parent. Rebuilding a Node from storage checks only what the Node alone shows.
    """

    def __init__(
        self,
        *,
        node_id: NodeIdentifier,
        name: str,
        layer_index: LayerIndex,
        parent_node_id: NodeIdentifier | None,
        activity_area: str,
        reporting_rule: str,
        confidentiality: ConfidentialityLevel,
        is_internal_structure_tracked: bool,
    ) -> None:
        """Rebuild a Node, for example from storage. Use `register` for a new Node.

        Args:
            node_id: Stable id, such as `sp12_inspection_team`.
            name: Display name, such as "SP-12 Inspection Team".
            layer_index: The one Layer the Node belongs to.
            parent_node_id: The Node it reports to; None only in Layer 0.
            activity_area: What the Node works on.
            reporting_rule: How often it reports to its parent, such as `weekly`.
            confidentiality: The visibility limit of the Node's knowledge.
            is_internal_structure_tracked: Whether the Node's children are modelled.

        Raises:
            ParentNodeRequiredError: The Node is below Layer 0 and has no parent.
            TopLayerNodeHasParentError: The Node is in Layer 0 and has a parent.
        """
        _check_parent_presence(node_id, layer_index, parent_node_id)
        self._node_id = node_id
        self._name = name
        self._layer_index = layer_index
        self._parent_node_id = parent_node_id
        self._activity_area = activity_area
        self._reporting_rule = reporting_rule
        self._confidentiality = confidentiality
        self._is_internal_structure_tracked = is_internal_structure_tracked
        self._pending_events: list[DomainEvent] = []

    @classmethod
    def register(
        cls,
        *,
        node_id: NodeIdentifier,
        name: str,
        layer_index: LayerIndex,
        parent: "Node | None",
        activity_area: str,
        reporting_rule: str,
        confidentiality: ConfidentialityLevel,
        is_internal_structure_tracked: bool,
        registered_at: datetime,
    ) -> "Node":
        """Add a new Node to the hierarchy under `parent` (spec §6.1).

        The Node records `NodeRegistered`; take it with `pull_events` after saving.

        Args:
            parent: The registered Node it reports to; None only in Layer 0.

        Raises:
            ParentNodeRequiredError: The Node is below Layer 0 and has no parent.
            TopLayerNodeHasParentError: The Node is in Layer 0 and has a parent.
            ParentNodeNotInHigherLayerError: The parent is not in a higher Layer.
            ParentStructureNotTrackedError: The parent's inside is outside the system
                boundary, so it cannot have children.
        """
        node = cls(
            node_id=node_id,
            name=name,
            layer_index=layer_index,
            parent_node_id=parent.node_id if parent else None,
            activity_area=activity_area,
            reporting_rule=reporting_rule,
            confidentiality=confidentiality,
            is_internal_structure_tracked=is_internal_structure_tracked,
        )
        if parent is not None:
            parent.check_can_take_child(node)
        node._pending_events.append(
            NodeRegistered(
                occurred_at=registered_at,
                node_id=node_id,
                layer_index=layer_index,
                parent_node_id=node.parent_node_id,
            )
        )
        return node

    @property
    def node_id(self) -> NodeIdentifier:
        """Stable id of the Node. It never changes."""
        return self._node_id

    @property
    def name(self) -> str:
        """Display name of the Node."""
        return self._name

    @property
    def layer_index(self) -> LayerIndex:
        """The one Layer the Node belongs to."""
        return self._layer_index

    @property
    def parent_node_id(self) -> NodeIdentifier | None:
        """The Node it reports to; None only for the Layer 0 Node."""
        return self._parent_node_id

    @property
    def activity_area(self) -> str:
        """What the Node works on."""
        return self._activity_area

    @property
    def reporting_rule(self) -> str:
        """How often the Node reports to its parent, such as `weekly`."""
        return self._reporting_rule

    @property
    def confidentiality(self) -> ConfidentialityLevel:
        """The visibility limit of the Node's knowledge (spec §6.1)."""
        return self._confidentiality

    @property
    def is_internal_structure_tracked(self) -> bool:
        """Whether the Node's children are modelled, so it can have children."""
        return self._is_internal_structure_tracked

    def check_can_take_child(self, child: "Node") -> None:
        """Check that `child` may sit directly under this Node.

        Raises:
            ParentNodeNotInHigherLayerError: This Node is not in a higher Layer.
            ParentStructureNotTrackedError: This Node's inside is outside the system
                boundary.
        """
        if not self._layer_index.is_above(child.layer_index):
            raise ParentNodeNotInHigherLayerError(
                node_id=child.node_id.value,
                layer_index=child.layer_index.value,
                parent_node_id=self._node_id.value,
                parent_layer_index=self._layer_index.value,
            )
        if not self._is_internal_structure_tracked:
            raise ParentStructureNotTrackedError(
                node_id=child.node_id.value, parent_node_id=self._node_id.value
            )

    def pull_events(self) -> tuple[DomainEvent, ...]:
        """Return the events recorded since the last call, and forget them."""
        events = tuple(self._pending_events)
        self._pending_events.clear()
        return events

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Node) and other.node_id == self._node_id

    def __hash__(self) -> int:
        return hash(self._node_id)


def _check_parent_presence(
    node_id: NodeIdentifier, layer_index: LayerIndex, parent_node_id: NodeIdentifier | None
) -> None:
    if layer_index.is_top and parent_node_id is not None:
        raise TopLayerNodeHasParentError(node_id=node_id.value, parent_node_id=parent_node_id.value)
    if not layer_index.is_top and parent_node_id is None:
        raise ParentNodeRequiredError(node_id=node_id.value, layer_index=layer_index.value)
