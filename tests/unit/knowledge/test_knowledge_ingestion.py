from datetime import UTC, datetime, timedelta

import pytest

from offline_rag.knowledge.domain.errors import InvalidIngestionTransitionError
from offline_rag.knowledge.domain.knowledge_ingestion import IngestionStatus, KnowledgeIngestion
from offline_rag.knowledge.domain.version_tag import VersionTag

NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
LATER = NOW + timedelta(minutes=1)


def _queued() -> KnowledgeIngestion:
    return KnowledgeIngestion.queue(
        ingestion_id="ing-1", item_id="ki-1", version_tag=VersionTag("v1"), queued_at=NOW
    )


def _extracting() -> KnowledgeIngestion:
    ingestion = _queued()
    ingestion.start_extraction(NOW)
    return ingestion


def _reading_pages() -> KnowledgeIngestion:
    ingestion = _extracting()
    ingestion.wait_for_page_reading(NOW)
    return ingestion


def _chunking() -> KnowledgeIngestion:
    ingestion = _extracting()
    ingestion.wait_for_chunking(NOW)
    return ingestion


def _completed() -> KnowledgeIngestion:
    ingestion = _chunking()
    ingestion.complete(blocks_for_review=0, chunk_count=0, now=NOW)
    return ingestion


def _failed() -> KnowledgeIngestion:
    ingestion = _queued()
    ingestion.fail(failure_code="X", failure_detail="x", now=NOW)
    return ingestion


def test_new_ingestion_is_queued_with_no_attempts_when_created():
    ingestion = _queued()

    assert (ingestion.status, ingestion.attempts, ingestion.is_running) == (
        IngestionStatus.QUEUED,
        0,
        True,
    )


def test_attempts_are_counted_when_extraction_starts_again_after_a_redelivery():
    ingestion = _extracting()

    ingestion.start_extraction(LATER)

    assert (ingestion.status, ingestion.attempts, ingestion.updated_at) == (
        IngestionStatus.EXTRACTING,
        2,
        LATER,
    )


def test_page_reading_counts_an_attempt_when_it_starts():
    ingestion = _reading_pages()

    ingestion.start_page_reading(LATER)

    assert (ingestion.status, ingestion.attempts) == (IngestionStatus.READING_PAGES, 2)


@pytest.mark.parametrize("build", [_extracting, _reading_pages])
def test_run_waits_for_chunking_when_content_is_stored(build):  # type: ignore[no-untyped-def]
    ingestion = build()

    ingestion.wait_for_chunking(LATER)

    assert (ingestion.status, ingestion.is_running, ingestion.updated_at) == (
        IngestionStatus.CHUNKING,
        True,
        LATER,
    )


def test_chunking_counts_an_attempt_when_it_starts_again_after_a_redelivery():
    ingestion = _chunking()
    ingestion.start_chunking(NOW)

    ingestion.start_chunking(LATER)

    assert (ingestion.status, ingestion.attempts) == (IngestionStatus.CHUNKING, 3)


def test_run_completes_with_review_and_chunk_counts_when_chunking_finishes():
    ingestion = _chunking()

    ingestion.complete(blocks_for_review=3, chunk_count=7, now=LATER)

    assert (
        ingestion.status,
        ingestion.blocks_for_review,
        ingestion.chunk_count,
        ingestion.is_running,
    ) == (IngestionStatus.COMPLETED, 3, 7, False)


@pytest.mark.parametrize("build", [_queued, _extracting, _reading_pages, _chunking])
def test_run_records_the_error_when_it_fails_while_running(build):  # type: ignore[no-untyped-def]
    ingestion = build()

    ingestion.fail(failure_code="KNOWLEDGE_EXTRACTION_FAILED", failure_detail="Damaged.", now=LATER)

    assert (ingestion.status, ingestion.failure_code, ingestion.failure_detail) == (
        IngestionStatus.FAILED,
        "KNOWLEDGE_EXTRACTION_FAILED",
        "Damaged.",
    )


@pytest.mark.parametrize(
    ("build", "move"),
    [
        (_queued, lambda i: i.complete(blocks_for_review=0, chunk_count=0, now=LATER)),
        (_queued, lambda i: i.wait_for_page_reading(LATER)),
        (_queued, lambda i: i.start_page_reading(LATER)),
        (_queued, lambda i: i.wait_for_chunking(LATER)),
        (_queued, lambda i: i.start_chunking(LATER)),
        (_extracting, lambda i: i.complete(blocks_for_review=0, chunk_count=0, now=LATER)),
        (_extracting, lambda i: i.start_chunking(LATER)),
        (_reading_pages, lambda i: i.start_extraction(LATER)),
        (_reading_pages, lambda i: i.complete(blocks_for_review=0, chunk_count=0, now=LATER)),
        (_chunking, lambda i: i.start_extraction(LATER)),
        (_chunking, lambda i: i.wait_for_page_reading(LATER)),
        (_completed, lambda i: i.start_extraction(LATER)),
        (_completed, lambda i: i.start_chunking(LATER)),
        (_completed, lambda i: i.fail(failure_code="X", failure_detail="x", now=LATER)),
        (_failed, lambda i: i.complete(blocks_for_review=0, chunk_count=0, now=LATER)),
    ],
)
def test_status_is_kept_when_a_move_is_not_allowed(build, move):  # type: ignore[no-untyped-def]
    ingestion = build()
    status_before = ingestion.status

    with pytest.raises(InvalidIngestionTransitionError) as caught:
        move(ingestion)

    assert ingestion.status == status_before
    assert caught.value.details["from_status"] == status_before.value
