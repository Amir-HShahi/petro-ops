"""KnowledgeIngestion: one run of the pipeline that reads a KnowledgeVersion (ADR 0005)."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from offline_rag.knowledge.domain.errors import InvalidIngestionTransitionError
from offline_rag.knowledge.domain.version_tag import VersionTag


class IngestionStatus(StrEnum):
    """Where an ingestion stands. COMPLETED and FAILED are final."""

    QUEUED = "queued"
    EXTRACTING = "extracting"
    READING_PAGES = "reading_pages"
    CHUNKING = "chunking"
    COMPLETED = "completed"
    FAILED = "failed"


_RUNNING = frozenset(
    {
        IngestionStatus.QUEUED,
        IngestionStatus.EXTRACTING,
        IngestionStatus.READING_PAGES,
        IngestionStatus.CHUNKING,
    }
)


@dataclass(kw_only=True)
class KnowledgeIngestion:
    """One run of extraction, LVM page reading when needed, and chunking, for one version.

    The steps run in this order: QUEUED, EXTRACTING, READING_PAGES (only for PDF
    pages without a text layer), CHUNKING, then COMPLETED. Messages can arrive
    twice, so a step may start again from the state it set itself: extraction
    from EXTRACTING, page reading from READING_PAGES, chunking from CHUNKING.

    Attributes:
        attempts: How many times a step of this run has started.
        blocks_for_review: Blocks a person must check; set when COMPLETED.
        chunk_count: How many KnowledgeChunks the version was cut into; set when COMPLETED.
        failure_code: The error code that ended the run; set when FAILED.
        failure_detail: A short description of that error; set when FAILED.
        request_id: The request that started the run, for tracing logs.
    """

    ingestion_id: str
    item_id: str
    version_tag: VersionTag
    status: IngestionStatus
    attempts: int
    created_at: datetime
    updated_at: datetime
    request_id: str | None = None
    blocks_for_review: int | None = None
    chunk_count: int | None = None
    failure_code: str | None = None
    failure_detail: str | None = None

    @classmethod
    def queue(
        cls,
        *,
        ingestion_id: str,
        item_id: str,
        version_tag: VersionTag,
        queued_at: datetime,
        request_id: str | None = None,
    ) -> "KnowledgeIngestion":
        """Start a run for a version, waiting for a text worker."""
        return cls(
            ingestion_id=ingestion_id,
            item_id=item_id,
            version_tag=version_tag,
            status=IngestionStatus.QUEUED,
            attempts=0,
            created_at=queued_at,
            updated_at=queued_at,
            request_id=request_id,
        )

    @property
    def is_running(self) -> bool:
        """Whether the run has not reached COMPLETED or FAILED yet."""
        return self.status in _RUNNING

    def start_extraction(self, now: datetime) -> None:
        """Mark that a text worker started extracting.

        Raises:
            InvalidIngestionTransitionError: The run is not QUEUED or EXTRACTING.
        """
        self._move({IngestionStatus.QUEUED, IngestionStatus.EXTRACTING}, IngestionStatus.EXTRACTING)
        self.attempts += 1
        self.updated_at = now

    def wait_for_page_reading(self, now: datetime) -> None:
        """Mark that pages without a text layer wait for the LVM.

        Raises:
            InvalidIngestionTransitionError: The run is not EXTRACTING.
        """
        self._move({IngestionStatus.EXTRACTING}, IngestionStatus.READING_PAGES)
        self.updated_at = now

    def start_page_reading(self, now: datetime) -> None:
        """Mark that the vision worker started reading pages.

        Raises:
            InvalidIngestionTransitionError: The run is not READING_PAGES.
        """
        self._move({IngestionStatus.READING_PAGES}, IngestionStatus.READING_PAGES)
        self.attempts += 1
        self.updated_at = now

    def wait_for_chunking(self, now: datetime) -> None:
        """Mark that the content is stored and waits for a chunking worker.

        Raises:
            InvalidIngestionTransitionError: The run is not extracting or reading pages.
        """
        self._move(
            {IngestionStatus.EXTRACTING, IngestionStatus.READING_PAGES}, IngestionStatus.CHUNKING
        )
        self.updated_at = now

    def start_chunking(self, now: datetime) -> None:
        """Mark that a chunking worker started cutting the content into chunks.

        Raises:
            InvalidIngestionTransitionError: The run is not CHUNKING.
        """
        self._move({IngestionStatus.CHUNKING}, IngestionStatus.CHUNKING)
        self.attempts += 1
        self.updated_at = now

    def complete(self, *, blocks_for_review: int, chunk_count: int, now: datetime) -> None:
        """End the run with the content and its chunks stored.

        Raises:
            InvalidIngestionTransitionError: The run is not CHUNKING.
        """
        self._move({IngestionStatus.CHUNKING}, IngestionStatus.COMPLETED)
        self.blocks_for_review = blocks_for_review
        self.chunk_count = chunk_count
        self.updated_at = now

    def fail(self, *, failure_code: str, failure_detail: str, now: datetime) -> None:
        """End the run with the error that stopped it.

        Raises:
            InvalidIngestionTransitionError: The run has already ended.
        """
        self._move(_RUNNING, IngestionStatus.FAILED)
        self.failure_code = failure_code
        self.failure_detail = failure_detail
        self.updated_at = now

    def _move(
        self, allowed_from: set[IngestionStatus] | frozenset[IngestionStatus], to: IngestionStatus
    ) -> None:
        if self.status not in allowed_from:
            raise InvalidIngestionTransitionError(
                self.ingestion_id, from_status=self.status.value, to_status=to.value
            )
        self.status = to
