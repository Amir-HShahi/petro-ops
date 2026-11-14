"""The Node registry read from the Organizational Hierarchy context (spec §6.1)."""

from offline_rag.issue.infrastructure.errors import NodeRegistryUnavailableError
from offline_rag.organization.application.node_queries import NodeQueries
from offline_rag.shared_kernel.errors import InfrastructureError
from offline_rag.shared_kernel.node_identifier import NodeIdentifier


class OrganizationNodeDirectory:
    """Asks Organizational Hierarchy whether a Node is registered.

    Issue Management only needs Node ids, so it reaches the other context through
    its read-only queries and turns its storage errors into an Issue error.
    """

    def __init__(self, node_queries: NodeQueries) -> None:
        """Read the Nodes through `node_queries`."""
        self._node_queries = node_queries

    def has_node(self, node_id: NodeIdentifier) -> bool:
        """Return whether this Node is registered.

        Raises:
            NodeRegistryUnavailableError: The registered Nodes cannot be read.
        """
        try:
            return self._node_queries.is_registered(node_id)
        except InfrastructureError as error:
            raise NodeRegistryUnavailableError from error
