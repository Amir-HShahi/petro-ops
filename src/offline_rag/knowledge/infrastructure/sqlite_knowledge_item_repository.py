"""KnowledgeItem storage in a local SQLite database (spec §17, ADR 0003)."""

import json
import sqlite3
from dataclasses import asdict, fields
from datetime import datetime
from pathlib import Path
from typing import Any

from offline_rag.knowledge.application.errors import KnowledgeItemNotFoundError
from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.knowledge_item import KnowledgeItem
from offline_rag.knowledge.domain.knowledge_scope import ConfidentialityLevel, KnowledgeScope
from offline_rag.knowledge.domain.knowledge_version import KnowledgeVersion
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.knowledge.infrastructure.sqlite_database import SqliteDatabase
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

_SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge_items (
    item_id TEXT PRIMARY KEY,
    owner_node_id TEXT NOT NULL,
    confidentiality TEXT NOT NULL,
    usage_scope TEXT,
    active_version_tag TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS knowledge_items_by_owner ON knowledge_items (owner_node_id);

CREATE TABLE IF NOT EXISTS knowledge_versions (
    item_id TEXT NOT NULL REFERENCES knowledge_items (item_id),
    version_tag TEXT NOT NULL,
    sequence_number INTEGER NOT NULL,
    source_file_name TEXT NOT NULL,
    source_file_reference TEXT NOT NULL,
    document_format TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    change_reason TEXT,
    previous_version_tag TEXT,
    diff_summary TEXT,
    PRIMARY KEY (item_id, version_tag),
    UNIQUE (item_id, sequence_number)
);
CREATE INDEX IF NOT EXISTS knowledge_versions_by_content_hash
    ON knowledge_versions (content_hash);
"""

_TUPLE_METADATA_FIELDS = {
    field.name for field in fields(MetadataRecord) if field.type == tuple[str, ...]
}


class SqliteKnowledgeItemRepository:
    """Stores each KnowledgeItem as one row, and each of its versions as a row of its own."""

    def __init__(self, database_path: Path) -> None:
        """Open the database, creating the file and its tables when they are missing.

        Raises:
            KnowledgeStorageError: The database cannot be created or opened.
        """
        self._database = SqliteDatabase(database_path, schema=_SCHEMA)

    def get_by_id(self, item_id: str) -> KnowledgeItem:
        """Return the item with all its versions, oldest first.

        Raises:
            KnowledgeItemNotFoundError: No item has this id.
            KnowledgeStorageError: The database cannot be read.
        """
        with self._database.transaction("get_by_id") as connection:
            item_row = connection.execute(
                "SELECT * FROM knowledge_items WHERE item_id = ?", (item_id,)
            ).fetchone()
            if item_row is None:
                raise KnowledgeItemNotFoundError(item_id)
            version_rows = connection.execute(
                "SELECT * FROM knowledge_versions WHERE item_id = ? ORDER BY sequence_number",
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
            connection.execute(
                "INSERT INTO knowledge_items VALUES (?, ?, ?, ?, ?)",
                (
                    item.item_id,
                    item.owner_node_id.value,
                    item.scope.confidentiality.value,
                    item.scope.usage_scope,
                    item.active_version.version_tag.value,
                ),
            )
            connection.executemany(
                "INSERT INTO knowledge_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [_version_to_row(item.item_id, version) for version in item.versions],
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
        json.dumps(asdict(version.metadata)),
        version.created_at.isoformat(),
        version.change_reason,
        previous.value if previous else None,
        version.diff_summary,
    )


def _version_from_row(row: sqlite3.Row) -> KnowledgeVersion:
    stored_metadata: dict[str, Any] = json.loads(row["metadata_json"])
    metadata_fields: dict[str, Any] = {
        name: tuple(value) if name in _TUPLE_METADATA_FIELDS else value
        for name, value in stored_metadata.items()
    }
    metadata = MetadataRecord(**metadata_fields)
    previous = row["previous_version_tag"]
    return KnowledgeVersion(
        version_tag=VersionTag(row["version_tag"]),
        sequence_number=row["sequence_number"],
        source_file_name=row["source_file_name"],
        source_file_reference=row["source_file_reference"],
        document_format=DocumentFormat(row["document_format"]),
        content_hash=row["content_hash"],
        metadata=metadata,
        created_at=datetime.fromisoformat(row["created_at"]),
        change_reason=row["change_reason"],
        previous_version_tag=VersionTag(previous) if previous else None,
        diff_summary=row["diff_summary"],
    )
