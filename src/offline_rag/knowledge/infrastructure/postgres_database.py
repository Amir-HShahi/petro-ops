"""The Postgres connection pool that the Knowledge Management repositories share (ADR 0004)."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from offline_rag.knowledge.infrastructure.errors import KnowledgeStorageError


class PostgresDatabase:
    """Lends pooled connections, one transaction at a time.

    The schema is created by the Alembic migrations, not here.
    """

    def __init__(self, url: str, *, pool_size: int, connect_timeout_s: int) -> None:
        """Create the pool. Connections are opened in the background, so this does not block.

        Args:
            url: A libpq connection URL on a loopback host.
            pool_size: The most connections open at once.
            connect_timeout_s: How long to wait for a connection before failing.
        """
        self._pool: ConnectionPool[psycopg.Connection[DictRow]] = ConnectionPool(
            url,
            min_size=1,
            max_size=pool_size,
            timeout=connect_timeout_s,
            kwargs={"row_factory": dict_row, "connect_timeout": connect_timeout_s},
            connection_class=psycopg.Connection[DictRow],
            open=True,
        )

    @contextmanager
    def transaction(self, operation: str) -> Iterator[psycopg.Connection[DictRow]]:
        """Yield a connection whose changes are committed together, or not at all.

        Raises:
            KnowledgeStorageError: Postgres failed or could not be reached during `operation`.
        """
        try:
            with self._pool.connection() as connection, connection.transaction():
                yield connection
        except psycopg.Error as error:
            # PoolTimeout is a psycopg.Error too, so an unreachable server lands here.
            raise KnowledgeStorageError(operation) from error

    def close(self) -> None:
        """Close every pooled connection."""
        self._pool.close()

    def __enter__(self) -> "PostgresDatabase":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()
