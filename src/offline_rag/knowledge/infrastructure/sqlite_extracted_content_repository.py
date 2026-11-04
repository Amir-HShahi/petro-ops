"""Extracted content stored in the local SQLite database, next to the KnowledgeItems (ADR 0003)."""

import json
import sqlite3
from pathlib import Path

from offline_rag.knowledge.application.errors import ExtractedContentNotFoundError
from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.extracted_content import (
    ContentBlock,
    ContentBlockKind,
    ContentSource,
    ExtractedContent,
)
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.knowledge.infrastructure.sqlite_database import SqliteDatabase

_SCHEMA = """
CREATE TABLE IF NOT EXISTS extracted_contents (
    item_id TEXT NOT NULL,
    version_tag TEXT NOT NULL,
    document_format TEXT NOT NULL,
    page_count INTEGER,
    PRIMARY KEY (item_id, version_tag)
);

CREATE TABLE IF NOT EXISTS content_blocks (
    item_id TEXT NOT NULL,
    version_tag TEXT NOT NULL,
    block_order INTEGER NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    page_number INTEGER,
    heading_path_json TEXT NOT NULL,
    table_rows_json TEXT NOT NULL,
    source TEXT NOT NULL,
    needs_human_review INTEGER NOT NULL DEFAULT 0,
    review_reason TEXT,
    PRIMARY KEY (item_id, version_tag, block_order),
    FOREIGN KEY (item_id, version_tag) REFERENCES extracted_contents (item_id, version_tag)
);
"""

# Columns added after the first release of the table, with their definitions.
# A database created before them gets them on start (ADR 0003).
_ADDED_BLOCK_COLUMNS = {
    "needs_human_review": "INTEGER NOT NULL DEFAULT 0",
    "review_reason": "TEXT",
}


class SqliteExtractedContentRepository:
    """Stores one row per extracted version and one row per block."""

    def __init__(self, database_path: Path) -> None:
        """Open the database, creating its tables when they are missing.

        Raises:
            KnowledgeStorageError: The database cannot be created or opened.
        """
        self._database = SqliteDatabase(database_path, schema=_SCHEMA)
        with self._database.transaction("migrate_schema") as connection:
            existing = {
                row["name"] for row in connection.execute("PRAGMA table_info(content_blocks)")
            }
            for column, definition in _ADDED_BLOCK_COLUMNS.items():
                if column not in existing:
                    connection.execute(
                        f"ALTER TABLE content_blocks ADD COLUMN {column} {definition}"
                    )

    def save(self, item_id: str, version_tag: VersionTag, content: ExtractedContent) -> None:
        """Replace the stored content of a version in one transaction.

        Raises:
            KnowledgeStorageError: The database cannot be written.
        """
        key = (item_id, version_tag.value)
        with self._database.transaction("save_extracted_content") as connection:
            connection.execute(
                "DELETE FROM content_blocks WHERE item_id = ? AND version_tag = ?", key
            )
            connection.execute(
                "DELETE FROM extracted_contents WHERE item_id = ? AND version_tag = ?", key
            )
            connection.execute(
                "INSERT INTO extracted_contents VALUES (?, ?, ?, ?)",
                (*key, content.document_format.value, content.page_count),
            )
            connection.executemany(
                "INSERT INTO content_blocks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(*key, *_block_to_row(block)) for block in content.blocks],
            )

    def get(self, item_id: str, version_tag: VersionTag) -> ExtractedContent:
        """Return the stored content of a version, blocks in reading order.

        Raises:
            ExtractedContentNotFoundError: Nothing was extracted from that version.
            KnowledgeStorageError: The database cannot be read.
        """
        key = (item_id, version_tag.value)
        with self._database.transaction("get_extracted_content") as connection:
            content_row = connection.execute(
                "SELECT * FROM extracted_contents WHERE item_id = ? AND version_tag = ?", key
            ).fetchone()
            if content_row is None:
                raise ExtractedContentNotFoundError(*key)
            block_rows = connection.execute(
                "SELECT * FROM content_blocks WHERE item_id = ? AND version_tag = ? "
                "ORDER BY block_order",
                key,
            ).fetchall()

        return ExtractedContent(
            document_format=DocumentFormat(content_row["document_format"]),
            page_count=content_row["page_count"],
            blocks=tuple(_block_from_row(row) for row in block_rows),
        )


def _block_to_row(block: ContentBlock) -> tuple[object, ...]:
    return (
        block.order,
        block.kind.value,
        block.text,
        block.page_number,
        json.dumps(list(block.heading_path)),
        json.dumps([list(row) for row in block.table_rows]),
        block.source.value,
        int(block.needs_human_review),
        block.review_reason,
    )


def _block_from_row(row: sqlite3.Row) -> ContentBlock:
    # Rows were normalized before they were stored, so they are rebuilt as they are.
    return ContentBlock(
        order=row["block_order"],
        kind=ContentBlockKind(row["kind"]),
        text=row["text"],
        page_number=row["page_number"],
        heading_path=tuple(json.loads(row["heading_path_json"])),
        table_rows=tuple(tuple(cells) for cells in json.loads(row["table_rows_json"])),
        source=ContentSource(row["source"]),
        needs_human_review=bool(row["needs_human_review"]),
        review_reason=row["review_reason"],
    )
