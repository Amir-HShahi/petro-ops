"""KnowledgeChunks in the local Postgres database (ADR 0009)."""

from collections.abc import Sequence
from dataclasses import asdict

from psycopg.rows import DictRow
from psycopg.types.json import Jsonb

from offline_rag.knowledge.domain.knowledge_chunk import KnowledgeChunk
from offline_rag.knowledge.domain.source_reference import SourceReference
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.knowledge.infrastructure.postgres_database import PostgresDatabase
from offline_rag.knowledge.infrastructure.postgres_knowledge_item_repository import (
    metadata_from_json,
)
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

_INSERT_CHUNK = """
INSERT INTO knowledge_chunk
    (item_id, version_tag, chunk_order, chunk_id, text, token_count, heading_path, page_start,
     page_end, first_block_order, last_block_order, metadata)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

_SELECT_ACTIVE_BY_OWNER = """
SELECT chunk.* FROM knowledge_chunk AS chunk
JOIN knowledge_item AS item
    ON item.item_id = chunk.item_id AND item.active_version_tag = chunk.version_tag
WHERE item.owner_node_id = %s
ORDER BY chunk.item_id, chunk.chunk_order
"""


class PostgresKnowledgeChunkRepository:
    """Stores one row per chunk. Whether a chunk is retrievable is read from its item."""

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def replace(
        self, item_id: str, version_tag: VersionTag, chunks: Sequence[KnowledgeChunk]
    ) -> None:
        """Replace the chunks of a version in one transaction.

        Raises:
            KnowledgeStorageError: The database cannot be written.
        """
        with self._database.transaction("replace_chunks") as connection:
            connection.execute(
                "DELETE FROM knowledge_chunk WHERE item_id = %s AND version_tag = %s",
                (item_id, version_tag.value),
            )
            with connection.cursor() as cursor:
                cursor.executemany(_INSERT_CHUNK, [_chunk_to_row(chunk) for chunk in chunks])

    def list_by_version(self, item_id: str, version_tag: VersionTag) -> list[KnowledgeChunk]:
        """Return the chunks of a version in order.

        Raises:
            KnowledgeStorageError: The database cannot be read.
        """
        with self._database.transaction("list_chunks") as connection:
            rows = connection.execute(
                "SELECT * FROM knowledge_chunk WHERE item_id = %s AND version_tag = %s"
                " ORDER BY chunk_order",
                (item_id, version_tag.value),
            ).fetchall()
        return [_chunk_from_row(row) for row in rows]

    def list_active_by_owner(self, owner_node_id: NodeIdentifier) -> list[KnowledgeChunk]:
        """Return the chunks of the active version of each item the Node owns.

        Raises:
            KnowledgeStorageError: The database cannot be read.
        """
        with self._database.transaction("list_active_chunks_by_owner") as connection:
            rows = connection.execute(_SELECT_ACTIVE_BY_OWNER, (owner_node_id.value,)).fetchall()
        return [_chunk_from_row(row) for row in rows]


def _chunk_to_row(chunk: KnowledgeChunk) -> tuple[object, ...]:
    reference = chunk.source_reference
    return (
        reference.item_id,
        reference.version_tag.value,
        chunk.order,
        chunk.chunk_id,
        chunk.text,
        chunk.token_count,
        Jsonb(list(reference.heading_path)),
        reference.page_start,
        reference.page_end,
        chunk.first_block_order,
        chunk.last_block_order,
        Jsonb(asdict(chunk.metadata)),
    )


def _chunk_from_row(row: DictRow) -> KnowledgeChunk:
    return KnowledgeChunk(
        chunk_id=row["chunk_id"],
        source_reference=SourceReference(
            item_id=row["item_id"],
            version_tag=VersionTag(row["version_tag"]),
            heading_path=tuple(row["heading_path"]),
            page_start=row["page_start"],
            page_end=row["page_end"],
        ),
        order=row["chunk_order"],
        text=row["text"],
        token_count=row["token_count"],
        first_block_order=row["first_block_order"],
        last_block_order=row["last_block_order"],
        metadata=metadata_from_json(row["metadata"]),
    )
