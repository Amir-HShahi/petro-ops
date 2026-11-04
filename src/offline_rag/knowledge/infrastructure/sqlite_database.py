"""The local SQLite file that the Knowledge Management repositories share (ADR 0003)."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from offline_rag.knowledge.infrastructure.errors import KnowledgeStorageError


class SqliteDatabase:
    """Opens one short-lived connection per transaction, so no connection is left open."""

    def __init__(self, path: Path, *, schema: str) -> None:
        """Open the database file, creating it and running `schema` on it.

        Args:
            path: The database file. Its folder is created when it is missing.
            schema: `CREATE ... IF NOT EXISTS` statements, safe to run on every start.

        Raises:
            KnowledgeStorageError: The file cannot be created or opened.
        """
        self._path = path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise KnowledgeStorageError(operation="create_schema") from error
        with self.transaction("create_schema") as connection:
            connection.executescript(schema)

    @contextmanager
    def transaction(self, operation: str) -> Iterator[sqlite3.Connection]:
        """Yield a connection whose changes are committed together, or not at all.

        Raises:
            KnowledgeStorageError: SQLite failed during `operation`.
        """
        # The connection context manager commits on success and rolls back on error;
        # `closing` then releases the file handle.
        try:
            with closing(sqlite3.connect(self._path)) as connection, connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys = ON")
                yield connection
        except sqlite3.Error as error:
            raise KnowledgeStorageError(operation) from error
