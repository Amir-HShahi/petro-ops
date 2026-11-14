from collections.abc import Iterator

import pytest

# The per-test migrated schema is shared with the knowledge integration tests.
from tests.integration.knowledge.conftest import postgres_url  # noqa: F401

from offline_rag.issue.infrastructure.postgres_database import PostgresDatabase


@pytest.fixture
def database(postgres_url: str) -> Iterator[PostgresDatabase]:  # noqa: F811
    with PostgresDatabase(postgres_url, pool_size=2, connect_timeout_s=2) as opened:
        yield opened
