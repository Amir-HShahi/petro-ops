from datetime import UTC, datetime

import psycopg
import pytest
from tests.integration.knowledge.conftest import migrate

from offline_rag.knowledge.application.ports import IngestionLane, OutboxMessage
from offline_rag.knowledge.domain.chunking import chunk_content
from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.duplicate_detection import DuplicateFlag, DuplicateKind
from offline_rag.knowledge.domain.extracted_content import ContentBlock, ExtractedContent
from offline_rag.knowledge.domain.knowledge_chunk import KnowledgeChunk
from offline_rag.knowledge.domain.knowledge_ingestion import IngestionStatus, KnowledgeIngestion
from offline_rag.knowledge.domain.knowledge_item import KnowledgeItem
from offline_rag.knowledge.domain.knowledge_scope import ConfidentialityLevel, KnowledgeScope
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.knowledge.infrastructure.errors import KnowledgeStorageError
from offline_rag.knowledge.infrastructure.postgres_database import PostgresDatabase
from offline_rag.knowledge.infrastructure.postgres_duplicate_flag_repository import (
    PostgresDuplicateFlagRepository,
)
from offline_rag.knowledge.infrastructure.postgres_knowledge_chunk_repository import (
    PostgresKnowledgeChunkRepository,
)
from offline_rag.knowledge.infrastructure.postgres_knowledge_ingestion_repository import (
    PostgresKnowledgeIngestionRepository,
)
from offline_rag.knowledge.infrastructure.postgres_knowledge_item_repository import (
    PostgresKnowledgeItemRepository,
)
from offline_rag.knowledge.infrastructure.postgres_version_fingerprint_repository import (
    PostgresVersionFingerprintRepository,
)
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
V1, V2 = VersionTag("v1"), VersionTag("v2")
TEAM = NodeIdentifier("sp12_inspection_team")
PLATFORM = NodeIdentifier("platform_sp12")
METADATA = MetadataRecord(document_type="inspection_report", tags=("riser", "ut"))
CONTENT = ExtractedContent(
    document_format=DocumentFormat.PDF,
    page_count=2,
    blocks=(
        ContentBlock.paragraph(order=0, text="Wall loss in the splash zone.", page_number=1),
        ContentBlock.paragraph(order=1, text="Coating has blistered.", page_number=2),
    ),
)


def _item(item_id: str, *, owner: NodeIdentifier = TEAM, content_hash: str = "") -> KnowledgeItem:
    return KnowledgeItem.submit(
        item_id=item_id,
        owner_node_id=owner,
        scope=KnowledgeScope(confidentiality=ConfidentialityLevel.INTERNAL),
        metadata=METADATA,
        source_file_name=f"{item_id}.pdf",
        source_file_reference=f"file-{item_id}",
        document_format=DocumentFormat.PDF,
        content_hash=content_hash or f"hash-{item_id}",
        submitted_at=NOW,
    )


def _chunks(item_id: str, version_tag: VersionTag = V1) -> tuple[KnowledgeChunk, ...]:
    return chunk_content(
        CONTENT,
        item_id=item_id,
        version_tag=version_tag,
        metadata=METADATA,
        count_tokens=len,
        target_tokens=25,
        max_tokens=40,
        overlap_share=0.0,
    )


def _flag(item_id: str, existing_item_id: str, kind: DuplicateKind) -> DuplicateFlag:
    return DuplicateFlag(
        item_id=item_id,
        version_tag=V1,
        kind=kind,
        existing_item_id=existing_item_id,
        existing_version_tag=V1,
        score=0.25,
        is_ambiguous=True,
    )


@pytest.fixture
def items(database: PostgresDatabase) -> PostgresKnowledgeItemRepository:
    repository = PostgresKnowledgeItemRepository(database)
    for item in (_item("ki-a"), _item("ki-b"), _item("ki-other", owner=PLATFORM)):
        repository.add(item)
    return repository


@pytest.fixture
def chunk_repository(database: PostgresDatabase) -> PostgresKnowledgeChunkRepository:
    return PostgresKnowledgeChunkRepository(database)


@pytest.fixture
def flags(database: PostgresDatabase) -> PostgresDuplicateFlagRepository:
    return PostgresDuplicateFlagRepository(database)


@pytest.fixture
def fingerprints(database: PostgresDatabase) -> PostgresVersionFingerprintRepository:
    return PostgresVersionFingerprintRepository(database)


@pytest.fixture
def ingestions(database: PostgresDatabase) -> PostgresKnowledgeIngestionRepository:
    return PostgresKnowledgeIngestionRepository(database)


def _new_version(items: PostgresKnowledgeItemRepository, item_id: str) -> KnowledgeItem:
    item = items.get_by_id(item_id)
    item.publish_version(
        source_file_name=f"{item_id}_v2.pdf",
        source_file_reference=f"file-{item_id}-v2",
        document_format=DocumentFormat.PDF,
        content_hash=f"hash-{item_id}-v2",
        metadata=METADATA,
        change_reason="Adds 3 readings.",
        published_at=NOW,
    )
    return item


def _queued(item_id: str, version_tag: VersionTag, ingestion_id: str) -> KnowledgeIngestion:
    return KnowledgeIngestion.queue(
        ingestion_id=ingestion_id, item_id=item_id, version_tag=version_tag, queued_at=NOW
    )


def _message(outbox_id: str, ingestion_id: str) -> OutboxMessage:
    return OutboxMessage(
        outbox_id=outbox_id, ingestion_id=ingestion_id, lane=IngestionLane.TEXT, created_at=NOW
    )


@pytest.mark.usefixtures("items")
def test_chunks_read_back_unchanged_when_stored(
    chunk_repository: PostgresKnowledgeChunkRepository,
):
    chunk_repository.replace("ki-a", V1, _chunks("ki-a"))

    assert tuple(chunk_repository.list_by_version("ki-a", V1)) == _chunks("ki-a")


@pytest.mark.usefixtures("items")
def test_old_chunks_are_replaced_when_a_version_is_chunked_again(
    chunk_repository: PostgresKnowledgeChunkRepository,
):
    chunk_repository.replace("ki-a", V1, _chunks("ki-a"))

    chunk_repository.replace("ki-a", V1, _chunks("ki-a")[:1])

    assert len(chunk_repository.list_by_version("ki-a", V1)) == 1


@pytest.mark.usefixtures("items")
def test_only_active_chunks_of_the_nodes_items_are_listed_when_asked(
    chunk_repository: PostgresKnowledgeChunkRepository,
    ingestions: PostgresKnowledgeIngestionRepository,
    items: PostgresKnowledgeItemRepository,
):
    for item_id in ("ki-a", "ki-b", "ki-other"):
        chunk_repository.replace(item_id, V1, _chunks(item_id))
    ingestions.add_with_version(
        _new_version(items, "ki-b"), _queued("ki-b", V2, "ing-b2"), _message("m-b2", "ing-b2")
    )

    listed = chunk_repository.list_active_by_owner(TEAM)

    assert {chunk.source_reference.item_id for chunk in listed} == {"ki-a"}


def test_chunks_are_refused_when_their_version_does_not_exist(
    chunk_repository: PostgresKnowledgeChunkRepository,
):
    with pytest.raises(KnowledgeStorageError):
        chunk_repository.replace("ki-missing", V1, _chunks("ki-missing"))


@pytest.mark.usefixtures("items")
def test_flags_read_back_ordered_by_item_when_stored(flags: PostgresDuplicateFlagRepository):
    stored = [
        _flag("ki-a", "ki-b", DuplicateKind.OVERLAP),
        _flag("ki-a", "ki-other", DuplicateKind.EXACT),
    ]

    flags.replace("ki-a", V1, list(reversed(stored)))

    assert flags.list_by_version("ki-a", V1) == stored


@pytest.mark.usefixtures("items")
def test_old_flags_are_replaced_when_a_version_is_checked_again(
    flags: PostgresDuplicateFlagRepository,
):
    flags.replace("ki-a", V1, [_flag("ki-a", "ki-b", DuplicateKind.OVERLAP)])

    flags.replace("ki-a", V1, [])

    assert flags.list_by_version("ki-a", V1) == []


@pytest.mark.usefixtures("items")
def test_text_hash_finds_the_version_when_saved(
    fingerprints: PostgresVersionFingerprintRepository,
):
    fingerprints.save_text_hash("ki-a", V1, "text-1")

    (found,) = fingerprints.find_by_text_hash(TEAM, "text-1")

    assert (found.item_id, found.version_tag, found.metadata) == ("ki-a", V1, METADATA)
    assert found.normalized_text_hash == "text-1"


@pytest.mark.usefixtures("items")
def test_content_hash_finds_only_versions_of_the_same_node_when_looked_up(
    fingerprints: PostgresVersionFingerprintRepository, items: PostgresKnowledgeItemRepository
):
    items.add(_item("ki-copy", content_hash="hash-ki-a"))
    items.add(_item("ki-elsewhere", owner=PLATFORM, content_hash="hash-ki-a"))

    found = fingerprints.find_by_content_hash(TEAM, "hash-ki-a")

    assert [fingerprint.item_id for fingerprint in found] == ["ki-a", "ki-copy"]


@pytest.mark.usefixtures("items")
def test_only_the_active_version_is_listed_when_an_item_has_two(
    fingerprints: PostgresVersionFingerprintRepository,
    ingestions: PostgresKnowledgeIngestionRepository,
    items: PostgresKnowledgeItemRepository,
):
    ingestions.add_with_version(
        _new_version(items, "ki-b"), _queued("ki-b", V2, "ing-b2"), _message("m-b2", "ing-b2")
    )

    listed = fingerprints.list_active_by_owner(TEAM)

    assert [(found.item_id, found.version_tag) for found in listed] == [("ki-a", V1), ("ki-b", V2)]


@pytest.mark.usefixtures("items")
def test_new_version_ingestion_and_flags_are_stored_together_when_a_version_is_added(
    ingestions: PostgresKnowledgeIngestionRepository,
    items: PostgresKnowledgeItemRepository,
    flags: PostgresDuplicateFlagRepository,
):
    item = _new_version(items, "ki-b")
    flag = DuplicateFlag(
        item_id="ki-b",
        version_tag=V2,
        kind=DuplicateKind.EXACT,
        existing_item_id="ki-a",
        existing_version_tag=V1,
        score=1.0,
    )

    ingestions.add_with_version(
        item, _queued("ki-b", V2, "ing-b2"), _message("m-b2", "ing-b2"), [flag]
    )

    stored = items.get_by_id("ki-b")
    assert stored.active_version.version_tag == V2
    assert stored.get_version(V2).change_reason == "Adds 3 readings."
    assert flags.list_by_version("ki-b", V2) == [flag]
    assert ingestions.get_by_id("ing-b2").version_tag == V2


@pytest.mark.usefixtures("items")
def test_nothing_is_stored_when_another_version_took_the_tag_first(
    ingestions: PostgresKnowledgeIngestionRepository, items: PostgresKnowledgeItemRepository
):
    seen_before = items.get_by_id("ki-b")
    ingestions.add_with_version(
        _new_version(items, "ki-b"), _queued("ki-b", V2, "ing-b2"), _message("m-b2", "ing-b2")
    )

    with pytest.raises(KnowledgeStorageError):
        ingestions.add_with_version(
            _second_version(seen_before), _queued("ki-b", V2, "ing-x"), _message("m-x", "ing-x")
        )

    assert items.get_by_id("ki-b").get_version(V2).source_file_reference == "file-ki-b-v2"


def _second_version(item: KnowledgeItem) -> KnowledgeItem:
    item.publish_version(
        source_file_name="other.pdf",
        source_file_reference="file-other",
        document_format=DocumentFormat.PDF,
        content_hash="hash-other",
        metadata=METADATA,
        change_reason="Other change.",
        published_at=NOW,
    )
    return item


@pytest.mark.usefixtures("items")
def test_chunk_count_reads_back_when_a_chunked_run_completes(
    ingestions: PostgresKnowledgeIngestionRepository,
):
    ingestion = _queued("ki-a", V1, "ing-a")
    ingestions.add(ingestion, _message("m-a", "ing-a"))
    ingestion.start_extraction(NOW)
    ingestion.wait_for_chunking(NOW)
    ingestion.complete(blocks_for_review=0, chunk_count=7, now=NOW)

    ingestions.save(ingestion)

    assert ingestions.get_by_id("ing-a").chunk_count == 7


@pytest.mark.usefixtures("items")
def test_second_running_ingestion_is_refused_when_the_first_is_chunking(
    ingestions: PostgresKnowledgeIngestionRepository,
):
    chunking = _queued("ki-a", V1, "ing-a")
    ingestions.add(chunking, _message("m-a", "ing-a"))
    chunking.start_extraction(NOW)
    chunking.wait_for_chunking(NOW)
    ingestions.save(chunking)

    with pytest.raises(KnowledgeStorageError):
        ingestions.add(_queued("ki-a", V1, "ing-a2"), _message("m-a2", "ing-a2"))
    assert ingestions.find_running("ki-a", V1) == ingestions.get_by_id("ing-a")


@pytest.mark.usefixtures("items")
def test_recent_ingestions_count_the_flags_of_their_version_when_listed(
    ingestions: PostgresKnowledgeIngestionRepository, flags: PostgresDuplicateFlagRepository
):
    ingestions.add(_queued("ki-a", V1, "ing-a"), _message("m-a", "ing-a"))
    flags.replace("ki-a", V1, [_flag("ki-a", "ki-b", DuplicateKind.OVERLAP)])

    (summary,) = ingestions.find_recent(5)

    assert summary.duplicate_flag_count == 1


def test_chunking_runs_go_back_to_queued_when_migration_0004_is_undone(postgres_url: str):
    with PostgresDatabase(postgres_url, pool_size=1, connect_timeout_s=2) as database:
        PostgresKnowledgeItemRepository(database).add(_item("ki-a"))
        repository = PostgresKnowledgeIngestionRepository(database)
        ingestion = _queued("ki-a", V1, "ing-a")
        repository.add(ingestion, _message("m-a", "ing-a"))
        ingestion.start_extraction(NOW)
        ingestion.wait_for_chunking(NOW)
        repository.save(ingestion)

    migrate(postgres_url, "0003", downgrade=True)

    with psycopg.connect(postgres_url) as connection:
        status = connection.execute(
            "SELECT status FROM knowledge_ingestion WHERE ingestion_id = 'ing-a'"
        ).fetchone()
        tables = connection.execute(
            "SELECT count(*) FROM information_schema.tables"
            " WHERE table_schema = current_schema()"
            " AND table_name IN ('knowledge_chunk', 'knowledge_duplicate_flag')"
        ).fetchone()
    assert status == (IngestionStatus.QUEUED.value,)
    assert tables == (0,)


def test_chunks_and_flags_are_stored_again_when_migration_0004_is_redone(postgres_url: str):
    migrate(postgres_url, "0003", downgrade=True)
    migrate(postgres_url)

    with PostgresDatabase(postgres_url, pool_size=1, connect_timeout_s=2) as database:
        PostgresKnowledgeItemRepository(database).add(_item("ki-a"))
        PostgresKnowledgeItemRepository(database).add(_item("ki-b"))
        chunks = PostgresKnowledgeChunkRepository(database)
        chunks.replace("ki-a", V1, _chunks("ki-a"))
        PostgresDuplicateFlagRepository(database).replace(
            "ki-a", V1, [_flag("ki-a", "ki-b", DuplicateKind.OVERLAP)]
        )

        assert len(chunks.list_by_version("ki-a", V1)) == len(_chunks("ki-a"))
