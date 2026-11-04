from datetime import UTC, datetime

import psycopg
import pytest

from offline_rag.knowledge.application.errors import KnowledgeIngestionNotFoundError
from offline_rag.knowledge.application.ports import IngestionLane, OutboxMessage
from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.knowledge_ingestion import IngestionStatus, KnowledgeIngestion
from offline_rag.knowledge.domain.knowledge_item import KnowledgeItem
from offline_rag.knowledge.domain.knowledge_scope import ConfidentialityLevel, KnowledgeScope
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.knowledge.infrastructure.errors import KnowledgeStorageError
from offline_rag.knowledge.infrastructure.postgres_database import PostgresDatabase
from offline_rag.knowledge.infrastructure.postgres_knowledge_ingestion_repository import (
    PostgresKnowledgeIngestionRepository,
)
from offline_rag.knowledge.infrastructure.postgres_knowledge_item_repository import (
    PostgresKnowledgeItemRepository,
)
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
V1 = VersionTag("v1")


def _item(item_id: str = "ki-1") -> KnowledgeItem:
    return KnowledgeItem.submit(
        item_id=item_id,
        owner_node_id=NodeIdentifier("sp12_inspection_team"),
        scope=KnowledgeScope(confidentiality=ConfidentialityLevel.INTERNAL),
        metadata=MetadataRecord(),
        source_file_name="report.pdf",
        source_file_reference="stored.pdf",
        document_format=DocumentFormat.PDF,
        content_hash="hash",
        submitted_at=NOW,
    )


def _ingestion(ingestion_id: str = "ing-1") -> KnowledgeIngestion:
    return KnowledgeIngestion.queue(
        ingestion_id=ingestion_id, item_id="ki-1", version_tag=V1, queued_at=NOW, request_id="r1"
    )


def _message(outbox_id: str, ingestion_id: str = "ing-1", lane=IngestionLane.TEXT) -> OutboxMessage:  # type: ignore[no-untyped-def]
    return OutboxMessage(outbox_id=outbox_id, ingestion_id=ingestion_id, lane=lane, created_at=NOW)


def _outbox(postgres_url: str) -> list[tuple[str, str, object]]:
    with psycopg.connect(postgres_url) as connection:
        return connection.execute(  # type: ignore[return-value]
            "SELECT outbox_id, routing_key, payload FROM outbox_message ORDER BY outbox_id"
        ).fetchall()


@pytest.fixture
def repository(database: PostgresDatabase) -> PostgresKnowledgeIngestionRepository:
    return PostgresKnowledgeIngestionRepository(database)


def test_item_ingestion_and_message_are_stored_together_when_added(
    repository: PostgresKnowledgeIngestionRepository, database: PostgresDatabase, postgres_url: str
):
    repository.add_with_item(_item(), _ingestion(), _message("m1"))

    assert PostgresKnowledgeItemRepository(database).get_by_id("ki-1") == _item()
    assert repository.get_by_id("ing-1") == _ingestion()
    assert _outbox(postgres_url) == [("m1", "text", {"ingestion_id": "ing-1", "outbox_id": "m1"})]


def test_nothing_is_stored_when_the_message_cannot_be_written(
    repository: PostgresKnowledgeIngestionRepository, database: PostgresDatabase
):
    repository.add_with_item(_item(), _ingestion(), _message("m1"))

    with pytest.raises(KnowledgeStorageError):
        repository.add_with_item(_item("ki-2"), _ingestion("ing-2"), _message("m1"))

    with pytest.raises(KnowledgeIngestionNotFoundError):
        repository.get_by_id("ing-2")


def test_new_state_and_next_message_are_stored_when_ingestion_is_saved(
    repository: PostgresKnowledgeIngestionRepository, postgres_url: str
):
    repository.add_with_item(_item(), _ingestion(), _message("m1"))
    ingestion = repository.get_by_id("ing-1")
    ingestion.start_extraction(NOW)
    ingestion.wait_for_page_reading(NOW)

    repository.save(ingestion, _message("m2", lane=IngestionLane.VISION))

    assert repository.get_by_id("ing-1") == ingestion
    assert [row[1] for row in _outbox(postgres_url)] == ["text", "vision"]


def test_running_ingestion_is_found_until_it_ends(repository: PostgresKnowledgeIngestionRepository):
    repository.add_with_item(_item(), _ingestion(), _message("m1"))
    assert repository.find_running("ki-1", V1) == _ingestion()

    ended = repository.get_by_id("ing-1")
    ended.fail(failure_code="X", failure_detail="x", now=NOW)
    repository.save(ended)

    assert repository.find_running("ki-1", V1) is None
    assert repository.get_by_id("ing-1").status == IngestionStatus.FAILED


def test_second_running_ingestion_of_a_version_is_refused_when_added(
    repository: PostgresKnowledgeIngestionRepository,
):
    repository.add_with_item(_item(), _ingestion(), _message("m1"))

    with pytest.raises(KnowledgeStorageError):
        repository.add(_ingestion("ing-2"), _message("m2", "ing-2"))


def test_lookup_raises_not_found_when_ingestion_is_missing(
    repository: PostgresKnowledgeIngestionRepository,
):
    with pytest.raises(KnowledgeIngestionNotFoundError):
        repository.get_by_id("ing-404")
