import uuid
from collections.abc import Iterator
from urllib.parse import quote

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from offline_rag.knowledge.infrastructure.postgres_database import PostgresDatabase
from offline_rag.settings import Settings


def migrate(database_url: str, revision: str = "head", *, downgrade: bool = False) -> None:
    config = Config()
    config.set_main_option("script_location", "offline_rag:migrations")
    config.attributes["database_url"] = database_url
    if downgrade:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


@pytest.fixture
def postgres_url() -> Iterator[str]:
    """Yield a URL to an empty, migrated schema of its own, dropped after the test.

    Each test gets a fresh schema, so the tables in DATABASE_URL are never touched.
    """
    base_url = Settings().database_url
    schema = f"test_{uuid.uuid4().hex[:12]}"
    try:
        with psycopg.connect(base_url, connect_timeout=2, autocommit=True) as connection:
            connection.execute(f'CREATE SCHEMA "{schema}"')
    except psycopg.OperationalError as error:
        pytest.skip(f"Postgres at DATABASE_URL is not reachable: {error}")

    separator = "&" if "?" in base_url else "?"
    url = f"{base_url}{separator}options={quote(f'-csearch_path={schema}')}"
    migrate(url)
    yield url
    with psycopg.connect(base_url, autocommit=True) as connection:
        connection.execute(f'DROP SCHEMA "{schema}" CASCADE')


@pytest.fixture
def database(postgres_url: str) -> Iterator[PostgresDatabase]:
    with PostgresDatabase(postgres_url, pool_size=2, connect_timeout_s=2) as opened:
        yield opened
