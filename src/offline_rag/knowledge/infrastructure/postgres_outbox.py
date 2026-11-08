"""The outbox_message table in the local Postgres database (ADR 0005)."""

from datetime import datetime

import psycopg
from psycopg.rows import DictRow
from psycopg.types.json import Jsonb

from offline_rag.knowledge.application.ports import IngestionLane, OutboxMessage
from offline_rag.knowledge.infrastructure.postgres_database import PostgresDatabase

_INSERT_MESSAGE = """
INSERT INTO outbox_message (outbox_id, ingestion_id, routing_key, payload, created_at)
VALUES (%s, %s, %s, %s, %s)
"""


class PostgresOutbox:
    """Reads unpublished messages and records when the broker stored them."""

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def find_unpublished(self, limit: int) -> list[OutboxMessage]:
        """Return up to `limit` messages not yet published, oldest first.

        Raises:
            KnowledgeStorageError: The database cannot be read.
        """
        with self._database.transaction("find_unpublished_messages") as connection:
            rows = connection.execute(
                "SELECT outbox_id, ingestion_id, routing_key, created_at FROM outbox_message"
                " WHERE published_at IS NULL ORDER BY created_at, outbox_id LIMIT %s",
                (limit,),
            ).fetchall()
        return [
            OutboxMessage(
                outbox_id=row["outbox_id"],
                ingestion_id=row["ingestion_id"],
                lane=IngestionLane(row["routing_key"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def mark_published(self, outbox_id: str, published_at: datetime) -> None:
        """Record that the broker has stored the message. A second call changes nothing.

        Raises:
            KnowledgeStorageError: The database cannot be written.
        """
        with self._database.transaction("mark_message_published") as connection:
            connection.execute(
                "UPDATE outbox_message SET published_at = %s"
                " WHERE outbox_id = %s AND published_at IS NULL",
                (published_at, outbox_id),
            )

    def add(self, message: OutboxMessage) -> None:
        """Store a message for an existing ingestion.

        Raises:
            KnowledgeStorageError: The database cannot be written, or the id is taken.
        """
        with self._database.transaction("add_message") as connection:
            insert_outbox_message(connection, message)

    def count_unpublished(self) -> int:
        """Return how many messages wait for the relay.

        Raises:
            KnowledgeStorageError: The database cannot be read.
        """
        with self._database.transaction("count_unpublished_messages") as connection:
            row = connection.execute(
                "SELECT count(*) AS unpublished FROM outbox_message WHERE published_at IS NULL"
            ).fetchone()
        return int(row["unpublished"]) if row else 0


def insert_outbox_message(connection: psycopg.Connection[DictRow], message: OutboxMessage) -> None:
    """Insert a message on an open connection, inside the caller's transaction."""
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
