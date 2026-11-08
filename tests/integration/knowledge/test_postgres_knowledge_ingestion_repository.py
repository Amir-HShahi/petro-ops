from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from offline_rag.knowledge.application.errors import (
    IngestionStatusChangedError,
    KnowledgeIngestionNotFoundError,
)
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
from offline_rag.knowledge.infrastructure.postgres_outbox import PostgresOutbox
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


LONG_AGO = NOW - timedelta(hours=1)
STALLED_SINCE = NOW - timedelta(minutes=30)


@pytest.fixture
def outbox(database: PostgresDatabase) -> PostgresOutbox:
    return PostgresOutbox(database)


def _queued_long_ago(
    repository: PostgresKnowledgeIngestionRepository,
    outbox: PostgresOutbox,
    *,
    is_published: bool = True,
) -> KnowledgeIngestion:
    ingestion = KnowledgeIngestion.queue(
        ingestion_id="ing-1", item_id="ki-1", version_tag=V1, queued_at=LONG_AGO
    )
    message = OutboxMessage(
        outbox_id="m1", ingestion_id="ing-1", lane=IngestionLane.TEXT, created_at=LONG_AGO
    )
    repository.add_with_item(_item(), ingestion, message)
    if is_published:
        outbox.mark_published("m1", LONG_AGO)
    return ingestion


def test_stalled_ingestion_is_found_when_published_message_brought_no_change(
    repository: PostgresKnowledgeIngestionRepository, outbox: PostgresOutbox
):
    queued = _queued_long_ago(repository, outbox)

    assert repository.find_stalled(STALLED_SINCE, limit=10) == [queued]


def test_ingestion_is_not_stalled_when_its_message_is_unpublished(
    repository: PostgresKnowledgeIngestionRepository, outbox: PostgresOutbox
):
    _queued_long_ago(repository, outbox, is_published=False)

    assert repository.find_stalled(STALLED_SINCE, limit=10) == []


def test_ingestion_is_not_stalled_when_a_message_was_sent_recently(
    repository: PostgresKnowledgeIngestionRepository, outbox: PostgresOutbox
):
    _queued_long_ago(repository, outbox)
    outbox.add(_message("m2"))
    outbox.mark_published("m2", NOW)

    assert repository.find_stalled(STALLED_SINCE, limit=10) == []


def test_ingestion_is_not_stalled_when_extracting(
    repository: PostgresKnowledgeIngestionRepository, outbox: PostgresOutbox
):
    ingestion = _queued_long_ago(repository, outbox)
    ingestion.start_extraction(LONG_AGO)
    repository.save(ingestion)

    assert repository.find_stalled(STALLED_SINCE, limit=10) == []


def test_page_reading_ingestion_is_stalled_when_vision_message_brought_no_change(
    repository: PostgresKnowledgeIngestionRepository, outbox: PostgresOutbox
):
    ingestion = _queued_long_ago(repository, outbox)
    ingestion.start_extraction(LONG_AGO)
    ingestion.wait_for_page_reading(LONG_AGO)
    vision = OutboxMessage(
        outbox_id="m2", ingestion_id="ing-1", lane=IngestionLane.VISION, created_at=LONG_AGO
    )
    repository.save(ingestion, vision)
    outbox.mark_published("m2", LONG_AGO)

    assert repository.find_stalled(STALLED_SINCE, limit=10) == [ingestion]


def test_ingestion_is_saved_when_its_status_is_still_the_expected_one(
    repository: PostgresKnowledgeIngestionRepository,
):
    repository.add_with_item(_item(), _ingestion(), _message("m1"))
    started = repository.get_by_id("ing-1")
    started.start_extraction(NOW)

    repository.save(started, expected_status=IngestionStatus.QUEUED)

    assert repository.get_by_id("ing-1").status == IngestionStatus.EXTRACTING


def test_second_start_is_refused_and_nothing_stored_when_status_has_moved_on(
    repository: PostgresKnowledgeIngestionRepository, postgres_url: str
):
    repository.add_with_item(_item(), _ingestion(), _message("m1"))
    first, second = repository.get_by_id("ing-1"), repository.get_by_id("ing-1")
    first.start_extraction(NOW)
    repository.save(first, expected_status=IngestionStatus.QUEUED)
    second.start_extraction(NOW)
    second.wait_for_page_reading(NOW)

    with pytest.raises(IngestionStatusChangedError):
        repository.save(
            second,
            _message("m2", lane=IngestionLane.VISION),
            expected_status=IngestionStatus.QUEUED,
        )

    assert repository.get_by_id("ing-1").status == IngestionStatus.EXTRACTING
    assert [row[0] for row in _outbox(postgres_url)] == ["m1"]


def test_recent_ingestions_come_newest_first_with_their_file_when_found(
    repository: PostgresKnowledgeIngestionRepository,
):
    repository.add_with_item(_item(), _ingestion(), _message("m1"))
    ended = repository.get_by_id("ing-1")
    ended.start_extraction(NOW)
    ended.complete(blocks_for_review=2, now=NOW)
    repository.save(ended)
    later = KnowledgeIngestion.queue(
        ingestion_id="ing-2", item_id="ki-1", version_tag=V1, queued_at=NOW + timedelta(minutes=1)
    )
    repository.add(later, _message("m2", "ing-2"))

    recent = repository.find_recent(10)

    assert [summary.ingestion for summary in recent] == [later, ended]
    assert {summary.source_file_name for summary in recent} == {"report.pdf"}
    assert {summary.document_format for summary in recent} == {DocumentFormat.PDF}


def test_recent_ingestions_stop_at_the_limit_when_there_are_more(
    repository: PostgresKnowledgeIngestionRepository,
):
    repository.add_with_item(_item(), _ingestion(), _message("m1"))
    repository.add_with_item(_item("ki-2"), _ingestion_of("ki-2", "ing-2"), _message("m2", "ing-2"))

    assert [summary.ingestion.ingestion_id for summary in repository.find_recent(1)] == ["ing-2"]


def test_no_recent_ingestions_are_found_when_none_exist(
    repository: PostgresKnowledgeIngestionRepository,
):
    assert repository.find_recent(10) == []


def _ingestion_of(item_id: str, ingestion_id: str) -> KnowledgeIngestion:
    return KnowledgeIngestion.queue(
        ingestion_id=ingestion_id,
        item_id=item_id,
        version_tag=V1,
        queued_at=NOW + timedelta(minutes=1),
    )
