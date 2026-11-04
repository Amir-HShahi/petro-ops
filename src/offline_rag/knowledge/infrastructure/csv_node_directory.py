"""The Node registry read from the CSV file of spec §6.1 (`fixtures/registry/nodes.csv`)."""

import csv
from pathlib import Path

from offline_rag.knowledge.infrastructure.errors import NodeRegistryUnavailableError
from offline_rag.shared_kernel.errors import InvalidNodeIdentifierError
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

_NODE_ID_COLUMN = "node_id"


class CsvNodeDirectory:
    """Reads the `node_id` column once, on the first lookup.

    This stands in for the Organizational Hierarchy context until it has its own
    store (phase 6).
    """

    def __init__(self, registry_path: Path) -> None:
        """Read the registry from `registry_path` when it is first needed."""
        self._registry_path = registry_path
        self._node_ids: frozenset[NodeIdentifier] | None = None

    def has_node(self, node_id: NodeIdentifier) -> bool:
        """Return whether the registry lists this Node.

        Raises:
            NodeRegistryUnavailableError: The file is missing, has no `node_id` column
                or lists an invalid Node id.
        """
        if self._node_ids is None:
            self._node_ids = self._read_node_ids()
        return node_id in self._node_ids

    def _read_node_ids(self) -> frozenset[NodeIdentifier]:
        try:
            with self._registry_path.open(newline="", encoding="utf-8") as registry:
                reader = csv.DictReader(registry)
                if _NODE_ID_COLUMN not in (reader.fieldnames or []):
                    raise NodeRegistryUnavailableError
                return frozenset(NodeIdentifier(row[_NODE_ID_COLUMN]) for row in reader)
        except (OSError, csv.Error, UnicodeDecodeError, InvalidNodeIdentifierError) as error:
            raise NodeRegistryUnavailableError from error
