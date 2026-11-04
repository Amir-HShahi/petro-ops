from datetime import UTC, datetime

import psycopg
import pytest

from offline_rag.knowledge.application.errors import KnowledgeItemNotFoundError
from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.knowledge_item import KnowledgeItem
from offline_rag.knowledge.domain.knowledge_scope import ConfidentialityLevel, KnowledgeScope
from offline_rag.knowledge.domain.knowledge_version import KnowledgeVersion
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.knowledge.infrastructure.errors import KnowledgeStorageError
from offline_rag.knowledge.infrastructure.postgres_database import PostgresDatabase
from offline_rag.knowledge.infrastructure.postgres_knowledge_item_repository import (
    PostgresKnowledgeItemRepository,
)
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

pytestmark = pytest.mark.integration

CREATED_AT = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
FULL_METADATA = MetadataRecord(
    domain="asset integrity",
    subdomain="corrosion",
    project="SP-12 riser R-3 integrity",
    author="L. Moradi",
    document_type="inspection_report",
    related_issue_ids=("riser_corrosion_sp12",),
    related_executor_ids=("prof-01", "prof-02"),
    related_rfp_ids=(),
    tags=("riser", "splash zone"),
    source_reliability="high",
)


def _version(sequence_number: int) -> KnowledgeVersion:
    return KnowledgeVersion(
        version_tag=VersionTag.for_sequence_number(sequence_number),
        sequence_number=sequence_number,
        source_file_name="inspection_sp12_riser_r3_2026.docx",
        source_file_reference=f"stored-{sequence_number}.docx",
        document_format=DocumentFormat.DOCX,
        content_hash=f"hash-{sequence_number}",
        metadata=FULL_METADATA,
        created_at=CREATED_AT,
        change_reason="Adds 3 readings" if sequence_number > 1 else None,
        previous_version_tag=(
            VersionTag.for_sequence_number(sequence_number - 1) if sequence_number > 1 else None
        ),
        diff_summary="Remaining life 2.2 → 1.4 years" if sequence_number > 1 else None,
    )


def _item(item_id: str = "ki-1") -> KnowledgeItem:
    return KnowledgeItem(
        item_id=item_id,
        owner_node_id=NodeIdentifier("sp12_inspection_team"),
        scope=KnowledgeScope(confidentiality=ConfidentialityLevel.CONFIDENTIAL, usage_scope="team"),
        versions=[_version(1), _version(2)],
        active_version_tag=VersionTag("v2"),
    )


@pytest.fixture
def repository(database: PostgresDatabase) -> PostgresKnowledgeItemRepository:
    return PostgresKnowledgeItemRepository(database)


def test_item_reads_back_unchanged_when_stored(repository: PostgresKnowledgeItemRepository):
    item = _item()

    repository.add(item)
    stored = repository.get_by_id("ki-1")

    assert stored.owner_node_id == item.owner_node_id
    assert stored.scope == item.scope
    assert stored.versions == item.versions
    assert stored.active_version.version_tag == VersionTag("v2")


def test_item_survives_a_new_pool_when_database_is_reopened(postgres_url: str):
    with PostgresDatabase(postgres_url, pool_size=1, connect_timeout_s=2) as first:
        PostgresKnowledgeItemRepository(first).add(_item())

    with PostgresDatabase(postgres_url, pool_size=1, connect_timeout_s=2) as reopened:
        assert PostgresKnowledgeItemRepository(reopened).get_by_id("ki-1").versions == (
            _item().versions
        )


def test_lookup_raises_not_found_when_item_is_missing(repository: PostgresKnowledgeItemRepository):
    with pytest.raises(KnowledgeItemNotFoundError):
        repository.get_by_id("ki-404")


def test_add_fails_and_keeps_the_first_item_when_id_is_taken(
    repository: PostgresKnowledgeItemRepository,
):
    repository.add(_item())

    with pytest.raises(KnowledgeStorageError) as caught:
        repository.add(_item())

    assert caught.value.code == "KNOWLEDGE_STORAGE_FAILED"
    assert caught.value.details == {"operation": "add"}
    assert len(repository.get_by_id("ki-1").versions) == 2


def test_add_writes_nothing_when_a_version_row_fails(
    postgres_url: str, repository: PostgresKnowledgeItemRepository
):
    with psycopg.connect(postgres_url, autocommit=True) as connection:
        connection.execute(
            "ALTER TABLE knowledge_version ADD CONSTRAINT reject_second_version"
            " CHECK (sequence_number < 2)"
        )

    with pytest.raises(KnowledgeStorageError):
        repository.add(_item())

    with pytest.raises(KnowledgeItemNotFoundError):
        repository.get_by_id("ki-1")


def test_lookup_fails_with_storage_error_when_server_is_unreachable():
    # Nothing listens on port 9.
    with PostgresDatabase(
        "postgresql://user@127.0.0.1:9/none", pool_size=1, connect_timeout_s=1
    ) as unreachable:
        repository = PostgresKnowledgeItemRepository(unreachable)

        with pytest.raises(KnowledgeStorageError) as caught:
            repository.get_by_id("ki-1")

    assert caught.value.details == {"operation": "get_by_id"}
