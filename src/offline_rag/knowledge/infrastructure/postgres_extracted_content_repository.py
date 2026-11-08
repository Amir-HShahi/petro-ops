"""Extracted content stored in local Postgres, next to the KnowledgeItems (ADR 0004)."""

from psycopg.rows import DictRow
from psycopg.types.json import Jsonb

from offline_rag.knowledge.application.errors import ExtractedContentNotFoundError
from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.extracted_content import (
    ContentBlock,
    ContentBlockKind,
    ContentSource,
    ExtractedContent,
)
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.knowledge.infrastructure.postgres_database import PostgresDatabase

_INSERT_BLOCK = """
INSERT INTO extracted_content_block
    (item_id, version_tag, block_order, kind, text, page_number, heading_path, table_rows,
     source, needs_human_review, review_reason)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


class PostgresExtractedContentRepository:
    """Stores one row per extracted version and one row per block."""

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def save(self, item_id: str, version_tag: VersionTag, content: ExtractedContent) -> None:
        """Replace the stored content of a version in one transaction.

        Raises:
            KnowledgeStorageError: The database cannot be written.
        """
        key = (item_id, version_tag.value)
        with self._database.transaction("save_extracted_content") as connection:
            # The blocks go with it through ON DELETE CASCADE.
            connection.execute(
                "DELETE FROM extracted_content WHERE item_id = %s AND version_tag = %s", key
            )
            connection.execute(
                "INSERT INTO extracted_content (item_id, version_tag, document_format, page_count)"
                " VALUES (%s, %s, %s, %s)",
                (*key, content.document_format.value, content.page_count),
            )
            with connection.cursor() as cursor:
                cursor.executemany(
                    _INSERT_BLOCK, [(*key, *_block_to_row(block)) for block in content.blocks]
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
                "SELECT * FROM extracted_content WHERE item_id = %s AND version_tag = %s", key
            ).fetchone()
            if content_row is None:
                raise ExtractedContentNotFoundError(*key)
            block_rows = connection.execute(
                "SELECT * FROM extracted_content_block WHERE item_id = %s AND version_tag = %s"
                " ORDER BY block_order",
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
        Jsonb(list(block.heading_path)),
        Jsonb([list(row) for row in block.table_rows]),
        block.source.value,
        block.needs_human_review,
        block.review_reason,
    )


def _block_from_row(row: DictRow) -> ContentBlock:
    # Rows were normalized before they were stored, so they are rebuilt as they are.
    return ContentBlock(
        order=row["block_order"],
        kind=ContentBlockKind(row["kind"]),
        text=row["text"],
        page_number=row["page_number"],
        heading_path=tuple(row["heading_path"]),
        table_rows=tuple(tuple(cells) for cells in row["table_rows"]),
        source=ContentSource(row["source"]),
        needs_human_review=row["needs_human_review"],
        review_reason=row["review_reason"],
    )
