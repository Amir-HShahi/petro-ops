"""Use case: add a Node to the organizational hierarchy (spec §6.1)."""

import structlog

from offline_rag.organization.application.commands import RegisterNode
from offline_rag.organization.application.errors import (
    NodeAlreadyRegisteredError,
    TopLayerNodeAlreadyRegisteredError,
)
from offline_rag.organization.application.ports import (
    Clock,
    EventPublisher,
    LayerRepository,
    NodeRepository,
)
from offline_rag.organization.domain.node import Node

log = structlog.get_logger()


class RegisterNodeHandler:
    """Registers a Node in its Layer, under a parent that may take it."""

    def __init__(
        self,
        *,
        node_repository: NodeRepository,
        layer_repository: LayerRepository,
        clock: Clock,
        event_publisher: EventPublisher,
    ) -> None:
        """Create the handler with the ports it needs."""
        self._node_repository = node_repository
        self._layer_repository = layer_repository
        self._clock = clock
        self._event_publisher = event_publisher

    def register(self, command: RegisterNode) -> Node:
        """Register the Node and return it.

        Raises:
            NodeAlreadyRegisteredError: The id is taken.
            LayerNotFoundError: The Layer is not in the registry.
            NodeNotFoundError: The parent Node is not registered.
            TopLayerNodeAlreadyRegisteredError: Layer 0 already has its Node.
            ParentNodeRequiredError: The Node is below Layer 0 and has no parent.
            TopLayerNodeHasParentError: The Node is in Layer 0 and has a parent.
            ParentNodeNotInHigherLayerError: The parent is not in a higher Layer.
            ParentStructureNotTrackedError: The parent cannot have children.
        """
        if self._node_repository.find_by_id(command.node_id) is not None:
            raise NodeAlreadyRegisteredError(command.node_id.value)
        self._layer_repository.get_by_index(command.layer_index)
        parent = (
            self._node_repository.get_by_id(command.parent_node_id)
            if command.parent_node_id is not None
            else None
        )
        if command.layer_index.is_top:
            self._check_top_layer_is_free(command)

        node = Node.register(
            node_id=command.node_id,
            name=command.name,
            layer_index=command.layer_index,
            parent=parent,
            activity_area=command.activity_area,
            reporting_rule=command.reporting_rule,
            confidentiality=command.confidentiality,
            is_internal_structure_tracked=command.is_internal_structure_tracked,
            registered_at=self._clock.now(),
        )
        self._node_repository.add(node)
        self._event_publisher.publish(node.pull_events())
        log.info(
            "node_registered",
            node_id=node.node_id.value,
            layer_index=node.layer_index.value,
            parent_node_id=node.parent_node_id.value if node.parent_node_id else None,
        )
        return node

    def _check_top_layer_is_free(self, command: RegisterNode) -> None:
        for existing in self._node_repository.find_all():
            if existing.layer_index.is_top:
                raise TopLayerNodeAlreadyRegisteredError(
                    node_id=command.node_id.value, top_node_id=existing.node_id.value
                )
