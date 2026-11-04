from datetime import UTC, datetime

import pytest
from tests.fakes.knowledge import (
    FakeClock,
    InMemoryKnowledgeIngestionRepository,
    InMemoryKnowledgeItemRepository,
)

from offline_rag.knowledge.application.commands import FailKnowledgeIngestion
from offline_rag.knowledge.application.errors import KnowledgeIngestionNotFoundError
from offline_rag.knowledge.application.fail_knowledge_ingestion import (
    FailKnowledgeIngestionHandler,
)
from offline_rag.knowledge.domain.knowledge_ingestion import IngestionStatus, KnowledgeIngestion
from offline_rag.knowledge.domain.version_tag import VersionTag

NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
COMMAND = FailKnowledgeIngestion(
    ingestion_id="ing-1",
    failure_code="KNOWLEDGE_MODEL_UNAVAILABLE",
    failure_detail="The model did not answer.",
)


@pytest.fixture
def ingestions() -> InMemoryKnowledgeIngestionRepository:
    repository = InMemoryKnowledgeIngestionRepository(InMemoryKnowledgeItemRepository())
    repository.ingestions["ing-1"] = KnowledgeIngestion.queue(
        ingestion_id="ing-1", item_id="ki-1", version_tag=VersionTag("v1"), queued_at=NOW
    )
    return repository


@pytest.fixture
def handler(ingestions: InMemoryKnowledgeIngestionRepository) -> FailKnowledgeIngestionHandler:
    return FailKnowledgeIngestionHandler(ingestion_repository=ingestions, clock=FakeClock(NOW))


def test_running_ingestion_is_stored_as_failed_when_retries_are_used_up(
    handler: FailKnowledgeIngestionHandler, ingestions: InMemoryKnowledgeIngestionRepository
):
    handler.fail(COMMAND)

    stored = ingestions.get_by_id("ing-1")
    assert (stored.status, stored.failure_code, stored.failure_detail) == (
        IngestionStatus.FAILED,
        "KNOWLEDGE_MODEL_UNAVAILABLE",
        "The model did not answer.",
    )


def test_completed_ingestion_stays_completed_when_a_late_failure_arrives(
    handler: FailKnowledgeIngestionHandler, ingestions: InMemoryKnowledgeIngestionRepository
):
    done = ingestions.get_by_id("ing-1")
    done.start_extraction(NOW)
    done.complete(blocks_for_review=0, now=NOW)
    ingestions.save(done)

    result = handler.fail(COMMAND)

    assert result.status == IngestionStatus.COMPLETED
    assert ingestions.get_by_id("ing-1").failure_code is None


def test_lookup_raises_not_found_when_ingestion_does_not_exist(
    handler: FailKnowledgeIngestionHandler,
):
    with pytest.raises(KnowledgeIngestionNotFoundError):
        handler.fail(
            FailKnowledgeIngestion(ingestion_id="ing-404", failure_code="X", failure_detail="x")
        )
