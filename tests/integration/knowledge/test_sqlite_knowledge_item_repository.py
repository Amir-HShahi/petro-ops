import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from offline_rag.knowledge.application.errors import KnowledgeItemNotFoundError
from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.knowledge_item import KnowledgeItem
from offline_rag.knowledge.domain.knowledge_scope import ConfidentialityLevel, KnowledgeScope
from offline_rag.knowledge.domain.knowledge_version import KnowledgeVersion
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.knowledge.infrastructure.errors import KnowledgeStorageError
from offline_rag.knowledge.infrastructure.sqlite_knowledge_item_repository import (
    SqliteKnowledgeItemRepository,
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
def database_path(tmp_path: Path) -> Path:
    return tmp_path / "data" / "knowledge.sqlite3"


def test_item_reads_back_unchanged_when_stored(database_path: Path):
    repository = SqliteKnowledgeItemRepository(database_path)
    item = _item()

    repository.add(item)
    stored = repository.get_by_id("ki-1")

    assert stored.owner_node_id == item.owner_node_id
    assert stored.scope == item.scope
    assert stored.versions == item.versions
    assert stored.active_version.version_tag == VersionTag("v2")


def test_item_survives_a_new_connection_when_database_is_reopened(database_path: Path):
    SqliteKnowledgeItemRepository(database_path).add(_item())

    reopened = SqliteKnowledgeItemRepository(database_path)

    assert reopened.get_by_id("ki-1").versions == _item().versions


def test_lookup_raises_not_found_when_item_is_missing(database_path: Path):
    repository = SqliteKnowledgeItemRepository(database_path)

    with pytest.raises(KnowledgeItemNotFoundError):
        repository.get_by_id("ki-404")


def test_add_fails_and_keeps_the_first_item_when_id_is_taken(database_path: Path):
    repository = SqliteKnowledgeItemRepository(database_path)
    repository.add(_item())

    with pytest.raises(KnowledgeStorageError) as caught:
        repository.add(_item())

    assert caught.value.code == "KNOWLEDGE_STORAGE_FAILED"
    assert caught.value.details == {"operation": "add"}
    assert len(repository.get_by_id("ki-1").versions) == 2


def test_add_writes_nothing_when_a_version_row_fails(database_path: Path):
    repository = SqliteKnowledgeItemRepository(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO knowledge_items VALUES ('other', 'platform_sp12', 'internal', NULL, 'v1')"
        )
        connection.execute(
            "INSERT INTO knowledge_versions VALUES "
            "('ki-1', 'v1', 1, 'a', 'b', 'pdf', 'h', '{}', '2026-01-01T00:00:00+00:00', "
            "NULL, NULL, NULL)"
        )

    with pytest.raises(KnowledgeStorageError):
        repository.add(_item())

    with pytest.raises(KnowledgeItemNotFoundError):
        repository.get_by_id("ki-1")


def test_opening_fails_with_storage_error_when_folder_cannot_be_created(tmp_path: Path):
    blocker = tmp_path / "data"
    blocker.write_text("a file where the data folder should be")

    with pytest.raises(KnowledgeStorageError) as caught:
        SqliteKnowledgeItemRepository(blocker / "knowledge.sqlite3")

    assert caught.value.details == {"operation": "create_schema"}
