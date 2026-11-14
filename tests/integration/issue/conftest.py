from collections.abc import Iterator
from pathlib import Path

import pytest

# The per-test migrated schema is shared with the knowledge integration tests.
from tests.integration.knowledge.conftest import postgres_url  # noqa: F401

from offline_rag.bootstrap import build_organization
from offline_rag.issue.infrastructure.postgres_database import PostgresDatabase
from offline_rag.organization.interface.node_registry_file import read_node_registry
from offline_rag.settings import Settings

ROOT = Path(__file__).parents[3]


@pytest.fixture
def database(postgres_url: str) -> Iterator[PostgresDatabase]:  # noqa: F811
    with PostgresDatabase(postgres_url, pool_size=2, connect_timeout_s=2) as opened:
        yield opened


@pytest.fixture
def settings(tmp_path: Path, postgres_url: str) -> Settings:  # noqa: F811
    """Return settings for a schema whose Nodes are the case-study registry.

    Nothing listens on the Ollama port, so a test never reaches a real model.
    """
    registered = Settings(
        data_dir=tmp_path / "data",
        database_url=postgres_url,
        node_registry_path=ROOT / "fixtures" / "registry" / "nodes.csv",
        prompts_dir=ROOT / "prompts",
        model_manifest_path=ROOT / "models" / "manifest.yaml",
        ollama_url="http://127.0.0.1:9",
        log_level="error",
    )
    organization = build_organization(registered)
    try:
        for command in read_node_registry(registered.node_registry_path):
            organization.register_node_handler.register(command)
    finally:
        organization.close()
    return registered
