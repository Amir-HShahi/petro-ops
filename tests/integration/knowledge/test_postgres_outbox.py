from datetime import UTC, datetime, timedelta

import pytest

from offline_rag.knowledge.application.ports import IngestionLane, OutboxMessage
from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.knowledge_ingestion import KnowledgeIngestion
from offline_rag.knowledge.domain.knowledge_item import KnowledgeItem
from offline_rag.knowledge.domain.knowledge_scope import ConfidentialityLevel, KnowledgeScope
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.knowledge.infrastructure.errors import KnowledgeStorageError
from offline_rag.knowledge.infrastructure.postgres_database import PostgresDatabase
from offline_rag.knowledge.infrastructure.postgres_knowledge_ingestion_repository import (
    PostgresKnowledgeIngestionRepository,
)
from offline_rag.knowledge.infrastructure.postgres_outbox import PostgresOutbox
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)


def _message(outbox_id: str, *, minutes_ago: int = 0, lane=IngestionLane.TEXT) -> OutboxMessage:  # type: ignore[no-untyped-def]
    return OutboxMessage(
        outbox_id=outbox_id,
        ingestion_id="ing-1",
        lane=lane,
        created_at=NOW - timedelta(minutes=minutes_ago),
    )


@pytest.fixture
def outbox(database: PostgresDatabase) -> PostgresOutbox:
    item = KnowledgeItem.submit(
        item_id="ki-1",
        owner_node_id=NodeIdentifier("sp12_inspection_team"),
        scope=KnowledgeScope(confidentiality=ConfidentialityLevel.INTERNAL),
        metadata=MetadataRecord(),
        source_file_name="report.pdf",
        source_file_reference="stored.pdf",
        document_format=DocumentFormat.PDF,
        content_hash="hash",
        submitted_at=NOW,
    )
    ingestion = KnowledgeIngestion.queue(
        ingestion_id="ing-1", item_id="ki-1", version_tag=VersionTag("v1"), queued_at=NOW
    )
    PostgresKnowledgeIngestionRepository(database).add_with_item(
        item, ingestion, _message("m-first", minutes_ago=10)
    )
    return PostgresOutbox(database)


def test_unpublished_messages_are_found_oldest_first_when_listed(outbox: PostgresOutbox):
    outbox.add(_message("m-vision", minutes_ago=1, lane=IngestionLane.VISION))

    assert outbox.find_unpublished(10) == [
        _message("m-first", minutes_ago=10),
        _message("m-vision", minutes_ago=1, lane=IngestionLane.VISION),
    ]


def test_only_limit_messages_are_found_when_more_are_waiting(outbox: PostgresOutbox):
    outbox.add(_message("m-second", minutes_ago=1))

    assert [message.outbox_id for message in outbox.find_unpublished(1)] == ["m-first"]


def test_published_message_is_not_found_again_when_marked(outbox: PostgresOutbox):
    outbox.mark_published("m-first", NOW)

    assert outbox.find_unpublished(10) == []


def test_marking_twice_keeps_the_first_publish_time_when_relay_repeats(
    outbox: PostgresOutbox, database: PostgresDatabase
):
    outbox.mark_published("m-first", NOW)
    outbox.mark_published("m-first", NOW + timedelta(hours=1))

    with database.transaction("read") as connection:
        row = connection.execute(
            "SELECT published_at FROM outbox_message WHERE outbox_id = 'm-first'"
        ).fetchone()
    assert row is not None
    assert row["published_at"] == NOW


def test_message_is_refused_when_its_ingestion_does_not_exist(outbox: PostgresOutbox):
    orphan = OutboxMessage(
        outbox_id="m-orphan", ingestion_id="ing-404", lane=IngestionLane.TEXT, created_at=NOW
    )

    with pytest.raises(KnowledgeStorageError):
        outbox.add(orphan)


def test_unpublished_messages_are_counted_when_some_were_published(outbox: PostgresOutbox):
    outbox.add(_message("m-second", minutes_ago=1))
    outbox.add(_message("m-third"))
    outbox.mark_published("m-first", NOW)

    assert outbox.count_unpublished() == 2


def test_no_unpublished_messages_are_counted_when_all_were_published(outbox: PostgresOutbox):
    outbox.mark_published("m-first", NOW)

    assert outbox.count_unpublished() == 0
