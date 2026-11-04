from datetime import UTC, datetime

import pytest
from tests.fakes.knowledge import (
    InMemoryExtractedContentRepository,
    InMemoryKnowledgeIngestionRepository,
    InMemoryKnowledgeItemRepository,
)

from offline_rag.knowledge.application.errors import (
    ExtractedContentNotFoundError,
    KnowledgeIngestionNotFoundError,
)
from offline_rag.knowledge.application.knowledge_ingestion_queries import (
    KnowledgeIngestionQueries,
)
from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.errors import KnowledgeVersionNotFoundError
from offline_rag.knowledge.domain.extracted_content import ContentBlock, ExtractedContent
from offline_rag.knowledge.domain.knowledge_ingestion import KnowledgeIngestion
from offline_rag.knowledge.domain.knowledge_item import KnowledgeItem
from offline_rag.knowledge.domain.knowledge_scope import ConfidentialityLevel, KnowledgeScope
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
V1 = VersionTag("v1")
CONTENT = ExtractedContent(
    document_format=DocumentFormat.DOCX,
    page_count=None,
    blocks=(ContentBlock.paragraph(order=0, text="Riser R-3 wall loss.", page_number=None),),
)


@pytest.fixture
def contents() -> InMemoryExtractedContentRepository:
    return InMemoryExtractedContentRepository()


@pytest.fixture
def queries(contents: InMemoryExtractedContentRepository) -> KnowledgeIngestionQueries:
    repository = InMemoryKnowledgeItemRepository()
    repository.add(
        KnowledgeItem.submit(
            item_id="ki-1",
            owner_node_id=NodeIdentifier("sp12_inspection_team"),
            scope=KnowledgeScope(confidentiality=ConfidentialityLevel.INTERNAL),
            metadata=MetadataRecord(),
            source_file_name="report.docx",
            source_file_reference="stored.docx",
            document_format=DocumentFormat.DOCX,
            content_hash="hash",
            submitted_at=NOW,
        )
    )
    ingestions = InMemoryKnowledgeIngestionRepository(repository)
    ingestions.ingestions["ing-1"] = KnowledgeIngestion.queue(
        ingestion_id="ing-1", item_id="ki-1", version_tag=V1, queued_at=NOW
    )
    return KnowledgeIngestionQueries(
        ingestion_repository=ingestions,
        repository=repository,
        extracted_content_repository=contents,
    )


def test_ingestion_is_returned_when_it_exists(queries: KnowledgeIngestionQueries):
    assert queries.get_ingestion("ing-1").item_id == "ki-1"


def test_lookup_raises_not_found_when_ingestion_does_not_exist(queries: KnowledgeIngestionQueries):
    with pytest.raises(KnowledgeIngestionNotFoundError):
        queries.get_ingestion("ing-404")


@pytest.mark.parametrize("version_tag", [None, V1])
def test_content_of_active_or_given_version_is_returned_when_extracted(
    queries: KnowledgeIngestionQueries,
    contents: InMemoryExtractedContentRepository,
    version_tag: VersionTag | None,
):
    contents.save("ki-1", V1, CONTENT)

    assert queries.get_content("ki-1", version_tag) == (V1, CONTENT)


@pytest.mark.parametrize(
    ("version_tag", "error"),
    [(V1, ExtractedContentNotFoundError), (VersionTag("v9"), KnowledgeVersionNotFoundError)],
)
def test_content_lookup_raises_when_version_has_no_content_or_does_not_exist(
    queries: KnowledgeIngestionQueries, version_tag: VersionTag, error: type[Exception]
):
    with pytest.raises(error):
        queries.get_content("ki-1", version_tag)
