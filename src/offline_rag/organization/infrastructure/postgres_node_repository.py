"""Node storage in the local Postgres database (spec §17, ADR 0004)."""

from typing import Any

from offline_rag.organization.application.errors import NodeNotFoundError
from offline_rag.organization.domain.node import Node
from offline_rag.organization.infrastructure.postgres_database import PostgresDatabase
from offline_rag.shared_kernel.confidentiality_level import ConfidentialityLevel
from offline_rag.shared_kernel.layer_index import LayerIndex
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

_INSERT_NODE = """
INSERT INTO node
    (node_id, name, layer_index, parent_node_id, activity_area, reporting_rule,
     confidentiality, is_internal_structure_tracked)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
"""


class PostgresNodeRepository:
    """Stores each Node as one row of the `node` table."""

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def get_by_id(self, node_id: NodeIdentifier) -> Node:
        """Return the Node with this id.

        Raises:
            NodeNotFoundError: No Node has this id.
            OrganizationStorageError: The database cannot be read.
        """
        node = self.find_by_id(node_id)
        if node is None:
            raise NodeNotFoundError(node_id.value)
        return node

    def find_by_id(self, node_id: NodeIdentifier) -> Node | None:
        """Return the Node with this id, or None if it is not registered.

        Raises:
            OrganizationStorageError: The database cannot be read.
        """
        with self._database.transaction("find_by_id") as connection:
            row = connection.execute(
                "SELECT * FROM node WHERE node_id = %s", (node_id.value,)
            ).fetchone()
        return _node_from_row(row) if row is not None else None

    def find_all(self) -> list[Node]:
        """Return every Node, from the top Layer down, then by id.

        Raises:
            OrganizationStorageError: The database cannot be read.
        """
        with self._database.transaction("find_all") as connection:
            rows = connection.execute("SELECT * FROM node ORDER BY layer_index, node_id").fetchall()
        return [_node_from_row(row) for row in rows]

    def add(self, node: Node) -> None:
        """Store a new Node.

        Raises:
            OrganizationStorageError: The database cannot be written, or the id is taken.
        """
        with self._database.transaction("add") as connection:
            connection.execute(
                _INSERT_NODE,
                (
                    node.node_id.value,
                    node.name,
                    node.layer_index.value,
                    node.parent_node_id.value if node.parent_node_id else None,
                    node.activity_area,
                    node.reporting_rule,
                    node.confidentiality.value,
                    node.is_internal_structure_tracked,
                ),
            )


def _node_from_row(row: dict[str, Any]) -> Node:
    parent_node_id = row["parent_node_id"]
    return Node(
        node_id=NodeIdentifier(row["node_id"]),
        name=row["name"],
        layer_index=LayerIndex(row["layer_index"]),
        parent_node_id=NodeIdentifier(parent_node_id) if parent_node_id else None,
        activity_area=row["activity_area"],
        reporting_rule=row["reporting_rule"],
        confidentiality=ConfidentialityLevel(row["confidentiality"]),
        is_internal_structure_tracked=row["is_internal_structure_tracked"],
    )
