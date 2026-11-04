"""KnowledgeIngestions and their outbox messages in the local Postgres database (ADR 0005)."""

import psycopg
from psycopg.rows import DictRow
from psycopg.types.json import Jsonb

from offline_rag.knowledge.application.errors import KnowledgeIngestionNotFoundError
from offline_rag.knowledge.application.ports import OutboxMessage
from offline_rag.knowledge.domain.knowledge_ingestion import IngestionStatus, KnowledgeIngestion
from offline_rag.knowledge.domain.knowledge_item import KnowledgeItem
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.knowledge.infrastructure.postgres_database import PostgresDatabase
from offline_rag.knowledge.infrastructure.postgres_knowledge_item_repository import (
    insert_knowledge_item,
)

_UPSERT_INGESTION = """
INSERT INTO knowledge_ingestion
    (ingestion_id, item_id, version_tag, status, attempts, blocks_for_review, failure_code,
     failure_detail, request_id, created_at, updated_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (ingestion_id) DO UPDATE SET
    status = EXCLUDED.status,
    attempts = EXCLUDED.attempts,
    blocks_for_review = EXCLUDED.blocks_for_review,
    failure_code = EXCLUDED.failure_code,
    failure_detail = EXCLUDED.failure_detail,
    updated_at = EXCLUDED.updated_at
"""

_INSERT_MESSAGE = """
INSERT INTO outbox_message (outbox_id, ingestion_id, routing_key, payload, created_at)
VALUES (%s, %s, %s, %s, %s)
"""


class PostgresKnowledgeIngestionRepository:
    """Stores each ingestion as one row, and each message in the outbox table beside it."""

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def add_with_item(
        self, item: KnowledgeItem, ingestion: KnowledgeIngestion, message: OutboxMessage
    ) -> None:
        """Store a new item, its first ingestion and the message, in one transaction.

        Raises:
            KnowledgeStorageError: The database cannot be written, or an id is taken.
        """
        with self._database.transaction("add_with_item") as connection:
            insert_knowledge_item(connection, item)
            _write(connection, ingestion, message)

    def add(self, ingestion: KnowledgeIngestion, message: OutboxMessage) -> None:
        """Store a new ingestion and its message in one transaction.

        Raises:
            KnowledgeStorageError: The database cannot be written, or the version
                already has a running ingestion.
        """
        with self._database.transaction("add_ingestion") as connection:
            _write(connection, ingestion, message)

    def save(self, ingestion: KnowledgeIngestion, message: OutboxMessage | None = None) -> None:
        """Store the ingestion's new state, and the message if any, in one transaction.

        Raises:
            KnowledgeStorageError: The database cannot be written.
        """
        with self._database.transaction("save_ingestion") as connection:
            _write(connection, ingestion, message)

    def get_by_id(self, ingestion_id: str) -> KnowledgeIngestion:
        """Return the ingestion with this id.

        Raises:
            KnowledgeIngestionNotFoundError: No ingestion has this id.
            KnowledgeStorageError: The database cannot be read.
        """
        with self._database.transaction("get_ingestion") as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_ingestion WHERE ingestion_id = %s", (ingestion_id,)
            ).fetchone()
        if row is None:
            raise KnowledgeIngestionNotFoundError(ingestion_id)
        return _ingestion_from_row(row)

    def find_running(self, item_id: str, version_tag: VersionTag) -> KnowledgeIngestion | None:
        """Return the ingestion of this version that has not ended, if there is one.

        Raises:
            KnowledgeStorageError: The database cannot be read.
        """
        with self._database.transaction("find_running_ingestion") as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_ingestion WHERE item_id = %s AND version_tag = %s"
                " AND status IN ('queued', 'extracting', 'reading_pages')",
                (item_id, version_tag.value),
            ).fetchone()
        return _ingestion_from_row(row) if row else None


def _write(
    connection: psycopg.Connection[DictRow],
    ingestion: KnowledgeIngestion,
    message: OutboxMessage | None,
) -> None:
    connection.execute(
        _UPSERT_INGESTION,
        (
            ingestion.ingestion_id,
            ingestion.item_id,
            ingestion.version_tag.value,
            ingestion.status.value,
            ingestion.attempts,
            ingestion.blocks_for_review,
            ingestion.failure_code,
            ingestion.failure_detail,
            ingestion.request_id,
            ingestion.created_at,
            ingestion.updated_at,
        ),
    )
    if message is not None:
        connection.execute(
            _INSERT_MESSAGE,
            (
                message.outbox_id,
                message.ingestion_id,
                message.lane.value,
                Jsonb({"ingestion_id": message.ingestion_id, "outbox_id": message.outbox_id}),
                message.created_at,
            ),
        )


def _ingestion_from_row(row: DictRow) -> KnowledgeIngestion:
    return KnowledgeIngestion(
        ingestion_id=row["ingestion_id"],
        item_id=row["item_id"],
        version_tag=VersionTag(row["version_tag"]),
        status=IngestionStatus(row["status"]),
        attempts=row["attempts"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        request_id=row["request_id"],
        blocks_for_review=row["blocks_for_review"],
        failure_code=row["failure_code"],
        failure_detail=row["failure_detail"],
    )
