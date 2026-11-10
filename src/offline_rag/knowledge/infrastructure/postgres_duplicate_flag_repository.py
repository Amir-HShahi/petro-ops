"""DuplicateFlags in the local Postgres database (ADR 0010)."""

from collections.abc import Sequence

import psycopg
from psycopg.rows import DictRow

from offline_rag.knowledge.domain.duplicate_detection import DuplicateFlag, DuplicateKind
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.knowledge.infrastructure.postgres_database import PostgresDatabase

_INSERT_FLAG = """
INSERT INTO knowledge_duplicate_flag
    (item_id, version_tag, existing_item_id, existing_version_tag, kind, score, is_ambiguous)
VALUES (%s, %s, %s, %s, %s, %s, %s)
"""


class PostgresDuplicateFlagRepository:
    """Stores one row per flag, keyed by the flagged version and the item it repeats."""

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def replace(
        self, item_id: str, version_tag: VersionTag, flags: Sequence[DuplicateFlag]
    ) -> None:
        """Replace the flags of a version in one transaction.

        Raises:
            KnowledgeStorageError: The database cannot be written.
        """
        with self._database.transaction("replace_duplicate_flags") as connection:
            connection.execute(
                "DELETE FROM knowledge_duplicate_flag WHERE item_id = %s AND version_tag = %s",
                (item_id, version_tag.value),
            )
            insert_duplicate_flags(connection, flags)

    def list_by_version(self, item_id: str, version_tag: VersionTag) -> list[DuplicateFlag]:
        """Return the flags of a version, ordered by the item each one names.

        Raises:
            KnowledgeStorageError: The database cannot be read.
        """
        with self._database.transaction("list_duplicate_flags") as connection:
            rows = connection.execute(
                "SELECT * FROM knowledge_duplicate_flag WHERE item_id = %s AND version_tag = %s"
                " ORDER BY existing_item_id",
                (item_id, version_tag.value),
            ).fetchall()
        return [_flag_from_row(row) for row in rows]


def insert_duplicate_flags(
    connection: psycopg.Connection[DictRow], flags: Sequence[DuplicateFlag]
) -> None:
    """Insert flags on an open connection, inside the caller's transaction."""
    with connection.cursor() as cursor:
        cursor.executemany(
            _INSERT_FLAG,
            [
                (
                    flag.item_id,
                    flag.version_tag.value,
                    flag.existing_item_id,
                    flag.existing_version_tag.value,
                    flag.kind.value,
                    flag.score,
                    flag.is_ambiguous,
                )
                for flag in flags
            ],
        )


def _flag_from_row(row: DictRow) -> DuplicateFlag:
    return DuplicateFlag(
        item_id=row["item_id"],
        version_tag=VersionTag(row["version_tag"]),
        kind=DuplicateKind(row["kind"]),
        existing_item_id=row["existing_item_id"],
        existing_version_tag=VersionTag(row["existing_version_tag"]),
        score=row["score"],
        is_ambiguous=row["is_ambiguous"],
    )
