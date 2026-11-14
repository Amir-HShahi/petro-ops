"""Builds the ingestion API over in-memory fakes, for API tests of any context."""

from collections.abc import Sequence
from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi.testclient import TestClient
from tests.fakes.knowledge import (
    FakeClock,
    FakeIdGenerator,
    FakeIngestionQueueMonitor,
    FakeNodeDirectory,
    InMemoryEventPublisher,
    InMemoryExtractedContentRepository,
    InMemoryKnowledgeChunkRepository,
    InMemoryKnowledgeIngestionRepository,
    InMemoryOutbox,
    InMemorySourceFileStore,
    InMemoryVersionFingerprintRepository,
)

from offline_rag.knowledge.application.knowledge_ingestion_queries import (
    KnowledgeIngestionQueries,
)
from offline_rag.knowledge.application.publish_knowledge_version import (
    PublishKnowledgeVersionHandler,
)
from offline_rag.knowledge.application.reingest_knowledge_item import (
    ReingestKnowledgeItemHandler,
)
from offline_rag.knowledge.application.submit_knowledge_item import SubmitKnowledgeItemHandler
from offline_rag.knowledge.domain.duplicate_detection import DuplicateDetector
from offline_rag.knowledge.interface.api import create_app

NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
NODE_ID = "sp12_inspection_team"
MAX_FILE_MB = 1


def build_api_client(
    *,
    ingestions: InMemoryKnowledgeIngestionRepository,
    contents: InMemoryExtractedContentRepository,
    chunks: InMemoryKnowledgeChunkRepository,
    queue_monitor: FakeIngestionQueueMonitor,
    extra_routers: Sequence[APIRouter] = (),
) -> TestClient:
    """Return a client of the API over fakes, with the routes of other contexts mounted."""
    clock = FakeClock(NOW)
    id_generator = FakeIdGenerator()
    file_store = InMemorySourceFileStore()
    fingerprints = InMemoryVersionFingerprintRepository(ingestions.item_repository)
    detector = DuplicateDetector(
        overlap_chunk_similarity=0.4, ambiguous_from_similarity=0.25, min_chunk_share=0.2
    )
    app = create_app(
        submit_handler=SubmitKnowledgeItemHandler(
            ingestion_repository=ingestions,
            node_directory=FakeNodeDirectory([NODE_ID]),
            source_file_store=file_store,
            fingerprint_repository=fingerprints,
            detector=detector,
            clock=clock,
            id_generator=id_generator,
            event_publisher=InMemoryEventPublisher(),
            max_file_mb=MAX_FILE_MB,
        ),
        publish_version_handler=PublishKnowledgeVersionHandler(
            ingestion_repository=ingestions,
            repository=ingestions.item_repository,
            source_file_store=file_store,
            fingerprint_repository=fingerprints,
            detector=detector,
            clock=clock,
            id_generator=id_generator,
            event_publisher=InMemoryEventPublisher(),
            max_file_mb=MAX_FILE_MB,
        ),
        reingest_handler=ReingestKnowledgeItemHandler(
            ingestion_repository=ingestions,
            repository=ingestions.item_repository,
            clock=clock,
            id_generator=id_generator,
        ),
        queries=KnowledgeIngestionQueries(
            ingestion_repository=ingestions,
            repository=ingestions.item_repository,
            extracted_content_repository=contents,
            chunk_repository=chunks,
            duplicate_flag_repository=ingestions.flag_repository,
            outbox=InMemoryOutbox(ingestions),
            node_directory=FakeNodeDirectory([NODE_ID, "platform_sp12"]),
            queue_monitor=queue_monitor,
        ),
        max_file_mb=MAX_FILE_MB,
        min_page_text_chars=20,
        extra_routers=extra_routers,
    )
    return TestClient(app, raise_server_exceptions=False)
