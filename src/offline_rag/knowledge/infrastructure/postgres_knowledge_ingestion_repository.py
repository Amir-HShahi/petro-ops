"""KnowledgeIngestions and their outbox messages in the local Postgres database (ADR 0005)."""

from datetime import datetime

import psycopg
from psycopg.rows import DictRow

from offline_rag.knowledge.application.errors import (
    IngestionStatusChangedError,
    KnowledgeIngestionNotFoundError,
)
from offline_rag.knowledge.application.ports import KnowledgeIngestionSummary, OutboxMessage
from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.knowledge_ingestion import IngestionStatus, KnowledgeIngestion
from offline_rag.knowledge.domain.knowledge_item import KnowledgeItem
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.knowledge.infrastructure.postgres_database import PostgresDatabase
from offline_rag.knowledge.infrastructure.postgres_knowledge_item_repository import (
    insert_knowledge_item,
)
from offline_rag.knowledge.infrastructure.postgres_outbox import insert_outbox_message

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

_SELECT_STALLED = """
SELECT * FROM knowledge_ingestion AS ingestion
WHERE ingestion.status IN ('queued', 'reading_pages')
    AND ingestion.updated_at < %(stalled_since)s
    AND NOT EXISTS (
        SELECT 1 FROM outbox_message AS message
        WHERE message.ingestion_id = ingestion.ingestion_id
            AND (message.published_at IS NULL OR message.created_at >= %(stalled_since)s)
    )
ORDER BY ingestion.updated_at, ingestion.ingestion_id
LIMIT %(limit)s
"""

_SELECT_RECENT = """
SELECT ingestion.*, version.source_file_name, version.document_format
FROM knowledge_ingestion AS ingestion
JOIN knowledge_version AS version USING (item_id, version_tag)
ORDER BY ingestion.created_at DESC, ingestion.ingestion_id DESC
LIMIT %s
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

    def save(
        self,
        ingestion: KnowledgeIngestion,
        message: OutboxMessage | None = None,
        *,
        expected_status: IngestionStatus | None = None,
    ) -> None:
        """Store the ingestion's new state, and the message if any, in one transaction.

        Raises:
            IngestionStatusChangedError: The stored status is not `expected_status`.
            KnowledgeStorageError: The database cannot be written.
        """
        with self._database.transaction("save_ingestion") as connection:
            if expected_status is not None:
                # The row lock makes a second worker wait here, then see the new status.
                row = connection.execute(
                    "SELECT status FROM knowledge_ingestion WHERE ingestion_id = %s FOR UPDATE",
                    (ingestion.ingestion_id,),
                ).fetchone()
                if row is None or row["status"] != expected_status.value:
                    raise IngestionStatusChangedError(
                        ingestion.ingestion_id, expected_status=expected_status.value
                    )
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

    def find_stalled(self, stalled_since: datetime, limit: int) -> list[KnowledgeIngestion]:
        """Return QUEUED or READING_PAGES ingestions with no news since `stalled_since`.

        Raises:
            KnowledgeStorageError: The database cannot be read.
        """
        with self._database.transaction("find_stalled_ingestions") as connection:
            rows = connection.execute(
                _SELECT_STALLED, {"stalled_since": stalled_since, "limit": limit}
            ).fetchall()
        return [_ingestion_from_row(row) for row in rows]

    def find_recent(self, limit: int) -> list[KnowledgeIngestionSummary]:
        """Return up to `limit` ingestions with their file, the most recently created first.

        Raises:
            KnowledgeStorageError: The database cannot be read.
        """
        with self._database.transaction("find_recent_ingestions") as connection:
            rows = connection.execute(_SELECT_RECENT, (limit,)).fetchall()
        return [
            KnowledgeIngestionSummary(
                ingestion=_ingestion_from_row(row),
                source_file_name=row["source_file_name"],
                document_format=DocumentFormat(row["document_format"]),
            )
            for row in rows
        ]


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
        insert_outbox_message(connection, message)


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
