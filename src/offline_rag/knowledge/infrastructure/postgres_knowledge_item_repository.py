"""KnowledgeItem storage in the local Postgres database (spec §17, ADR 0004)."""

from dataclasses import asdict, fields
from typing import Any

import psycopg
from psycopg.rows import DictRow
from psycopg.types.json import Jsonb

from offline_rag.knowledge.application.errors import KnowledgeItemNotFoundError
from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.knowledge_item import KnowledgeItem
from offline_rag.knowledge.domain.knowledge_scope import ConfidentialityLevel, KnowledgeScope
from offline_rag.knowledge.domain.knowledge_version import KnowledgeVersion
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.knowledge.infrastructure.postgres_database import PostgresDatabase
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

_TUPLE_METADATA_FIELDS = {
    field.name for field in fields(MetadataRecord) if field.type == tuple[str, ...]
}

_INSERT_ITEM = """
INSERT INTO knowledge_item
    (item_id, owner_node_id, confidentiality, usage_scope, active_version_tag)
VALUES (%s, %s, %s, %s, %s)
"""

_INSERT_VERSION = """
INSERT INTO knowledge_version
    (item_id, version_tag, sequence_number, source_file_name, source_file_reference,
     document_format, content_hash, metadata, created_at, change_reason,
     previous_version_tag, diff_summary)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


class PostgresKnowledgeItemRepository:
    """Stores each KnowledgeItem as one row, and each of its versions as a row of its own."""

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def get_by_id(self, item_id: str) -> KnowledgeItem:
        """Return the item with all its versions, oldest first.

        Raises:
            KnowledgeItemNotFoundError: No item has this id.
            KnowledgeStorageError: The database cannot be read.
        """
        with self._database.transaction("get_by_id") as connection:
            item_row = connection.execute(
                "SELECT * FROM knowledge_item WHERE item_id = %s", (item_id,)
            ).fetchone()
            if item_row is None:
                raise KnowledgeItemNotFoundError(item_id)
            version_rows = connection.execute(
                "SELECT * FROM knowledge_version WHERE item_id = %s ORDER BY sequence_number",
                (item_id,),
            ).fetchall()

        return KnowledgeItem(
            item_id=item_row["item_id"],
            owner_node_id=NodeIdentifier(item_row["owner_node_id"]),
            scope=KnowledgeScope(
                confidentiality=ConfidentialityLevel(item_row["confidentiality"]),
                usage_scope=item_row["usage_scope"],
            ),
            versions=[_version_from_row(row) for row in version_rows],
            active_version_tag=VersionTag(item_row["active_version_tag"]),
        )

    def add(self, item: KnowledgeItem) -> None:
        """Store a new item and all its versions in one transaction.

        Raises:
            KnowledgeStorageError: The database cannot be written, or the id is taken.
        """
        with self._database.transaction("add") as connection:
            insert_knowledge_item(connection, item)


def insert_knowledge_item(connection: psycopg.Connection[DictRow], item: KnowledgeItem) -> None:
    """Insert an item and its versions inside the caller's transaction.

    The ingestion repository uses it to store a new item with its first ingestion.
    """
    connection.execute(
        _INSERT_ITEM,
        (
            item.item_id,
            item.owner_node_id.value,
            item.scope.confidentiality.value,
            item.scope.usage_scope,
            item.active_version.version_tag.value,
        ),
    )
    with connection.cursor() as cursor:
        cursor.executemany(
            _INSERT_VERSION, [_version_to_row(item.item_id, version) for version in item.versions]
        )


def _version_to_row(item_id: str, version: KnowledgeVersion) -> tuple[object, ...]:
    previous = version.previous_version_tag
    return (
        item_id,
        version.version_tag.value,
        version.sequence_number,
        version.source_file_name,
        version.source_file_reference,
        version.document_format.value,
        version.content_hash,
        Jsonb(asdict(version.metadata)),
        version.created_at,
        version.change_reason,
        previous.value if previous else None,
        version.diff_summary,
    )


def insert_newest_version(connection: psycopg.Connection[DictRow], item: KnowledgeItem) -> None:
    """Insert an existing item's newest version and record which version is active.

    Older versions are already stored and never change (spec §7.6).
    """
    connection.execute(_INSERT_VERSION, _version_to_row(item.item_id, item.versions[-1]))
    connection.execute(
        "UPDATE knowledge_item SET active_version_tag = %s WHERE item_id = %s",
        (item.active_version.version_tag.value, item.item_id),
    )


def metadata_from_json(stored_metadata: dict[str, Any]) -> MetadataRecord:
    """Return a MetadataRecord stored as a JSON object, with its lists as tuples again."""
    metadata_fields: dict[str, Any] = {
        name: tuple(value) if name in _TUPLE_METADATA_FIELDS else value
        for name, value in stored_metadata.items()
    }
    return MetadataRecord(**metadata_fields)


def _version_from_row(row: DictRow) -> KnowledgeVersion:
    previous = row["previous_version_tag"]
    return KnowledgeVersion(
        version_tag=VersionTag(row["version_tag"]),
        sequence_number=row["sequence_number"],
        source_file_name=row["source_file_name"],
        source_file_reference=row["source_file_reference"],
        document_format=DocumentFormat(row["document_format"]),
        content_hash=row["content_hash"],
        metadata=metadata_from_json(row["metadata"]),
        created_at=row["created_at"],
        change_reason=row["change_reason"],
        previous_version_tag=VersionTag(previous) if previous else None,
        diff_summary=row["diff_summary"],
    )
