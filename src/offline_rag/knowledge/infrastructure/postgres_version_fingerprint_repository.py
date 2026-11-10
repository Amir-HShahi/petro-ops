"""Version hashes of one Node read from the local Postgres database (ADR 0010)."""

from psycopg.rows import DictRow

from offline_rag.knowledge.domain.duplicate_detection import VersionFingerprint
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.knowledge.infrastructure.postgres_database import PostgresDatabase
from offline_rag.knowledge.infrastructure.postgres_knowledge_item_repository import (
    metadata_from_json,
)
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

_SELECT_FINGERPRINTS = """
SELECT version.item_id, version.version_tag, item.owner_node_id, version.content_hash,
    version.normalized_text_hash, version.metadata
FROM knowledge_version AS version
JOIN knowledge_item AS item USING (item_id)
WHERE item.owner_node_id = %s
"""
_ORDER = "ORDER BY version.item_id, version.sequence_number"


class PostgresVersionFingerprintRepository:
    """Reads and writes the hash columns of `knowledge_version`."""

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def save_text_hash(
        self, item_id: str, version_tag: VersionTag, normalized_text_hash: str | None
    ) -> None:
        """Record the normalized text hash of a version.

        Raises:
            KnowledgeStorageError: The database cannot be written.
        """
        with self._database.transaction("save_text_hash") as connection:
            connection.execute(
                "UPDATE knowledge_version SET normalized_text_hash = %s"
                " WHERE item_id = %s AND version_tag = %s",
                (normalized_text_hash, item_id, version_tag.value),
            )

    def find_by_content_hash(
        self, owner_node_id: NodeIdentifier, content_hash: str
    ) -> list[VersionFingerprint]:
        """Return every version of the Node's items with this file hash.

        Raises:
            KnowledgeStorageError: The database cannot be read.
        """
        return self._select(
            "find_by_content_hash",
            " AND version.content_hash = %s",
            (owner_node_id.value, content_hash),
        )

    def find_by_text_hash(
        self, owner_node_id: NodeIdentifier, normalized_text_hash: str
    ) -> list[VersionFingerprint]:
        """Return every version of the Node's items with this normalized text hash.

        Raises:
            KnowledgeStorageError: The database cannot be read.
        """
        return self._select(
            "find_by_text_hash",
            " AND version.normalized_text_hash = %s",
            (owner_node_id.value, normalized_text_hash),
        )

    def list_active_by_owner(self, owner_node_id: NodeIdentifier) -> list[VersionFingerprint]:
        """Return the active version of every item the Node owns.

        Raises:
            KnowledgeStorageError: The database cannot be read.
        """
        return self._select(
            "list_active_fingerprints",
            " AND version.version_tag = item.active_version_tag",
            (owner_node_id.value,),
        )

    def _select(
        self, operation: str, condition: str, parameters: tuple[str, ...]
    ) -> list[VersionFingerprint]:
        query = (
            f"{_SELECT_FINGERPRINTS}{condition} ORDER BY version.item_id, version.sequence_number"
        )
        with self._database.transaction(operation) as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [_fingerprint_from_row(row) for row in rows]


def _fingerprint_from_row(row: DictRow) -> VersionFingerprint:
    return VersionFingerprint(
        item_id=row["item_id"],
        version_tag=VersionTag(row["version_tag"]),
        owner_node_id=NodeIdentifier(row["owner_node_id"]),
        content_hash=row["content_hash"],
        normalized_text_hash=row["normalized_text_hash"],
        metadata=metadata_from_json(row["metadata"]),
    )
