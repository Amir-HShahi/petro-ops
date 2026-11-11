"""Read-only queries on the registered Nodes, for other bounded contexts to use."""

from offline_rag.organization.application.ports import NodeRepository
from offline_rag.shared_kernel.node_identifier import NodeIdentifier


class NodeQueries:
    """Answers which Nodes are registered, without handing out the Node aggregate."""

    def __init__(self, *, node_repository: NodeRepository) -> None:
        """Create the queries over the Node store."""
        self._node_repository = node_repository

    def is_registered(self, node_id: NodeIdentifier) -> bool:
        """Return whether a Node with this id is registered."""
        return self._node_repository.find_by_id(node_id) is not None

    def list_node_ids(self) -> list[NodeIdentifier]:
        """Return the ids of all registered Nodes, sorted by id."""
        return sorted(
            (node.node_id for node in self._node_repository.find_all()),
            key=lambda node_id: node_id.value,
        )
