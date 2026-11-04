import pytest
from tests.integration.knowledge.conftest import migrate

from offline_rag.knowledge.application.errors import ExtractedContentNotFoundError
from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.extracted_content import (
    ContentBlock,
    ContentSource,
    ExtractedContent,
)
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.knowledge.infrastructure.postgres_database import PostgresDatabase
from offline_rag.knowledge.infrastructure.postgres_extracted_content_repository import (
    PostgresExtractedContentRepository,
)

pytestmark = pytest.mark.integration

V1 = VersionTag("v1")
CONTENT = ExtractedContent(
    document_format=DocumentFormat.PDF,
    page_count=3,
    blocks=(
        ContentBlock.paragraph(order=0, text="Remaining life is about 1.4 years.", page_number=1),
        ContentBlock.table(
            order=1,
            rows=[["Location", "Measured (mm)"], ["R-3 EL +8.5 m", "20.1"]],
            page_number=2,
        ),
    ),
)


@pytest.fixture
def repository(database: PostgresDatabase) -> PostgresExtractedContentRepository:
    return PostgresExtractedContentRepository(database)


def test_content_reads_back_unchanged_when_saved(repository: PostgresExtractedContentRepository):
    repository.save("ki-1", V1, CONTENT)

    assert repository.get("ki-1", V1) == CONTENT


def test_old_blocks_are_replaced_when_version_is_saved_again(
    repository: PostgresExtractedContentRepository,
):
    repository.save("ki-1", V1, CONTENT)
    newer = ExtractedContent(
        document_format=DocumentFormat.PDF,
        page_count=1,
        blocks=(ContentBlock.paragraph(order=0, text="Only one block now.", page_number=1),),
    )

    repository.save("ki-1", V1, newer)

    assert repository.get("ki-1", V1) == newer


def test_versions_are_kept_apart_when_both_are_saved(
    repository: PostgresExtractedContentRepository,
):
    repository.save("ki-1", V1, CONTENT)
    empty_docx = ExtractedContent(document_format=DocumentFormat.DOCX, page_count=None, blocks=())

    repository.save("ki-1", VersionTag("v2"), empty_docx)

    assert repository.get("ki-1", V1) == CONTENT
    assert repository.get("ki-1", VersionTag("v2")) == empty_docx


def test_lookup_raises_not_found_when_nothing_was_extracted(
    repository: PostgresExtractedContentRepository,
):
    with pytest.raises(ExtractedContentNotFoundError) as caught:
        repository.get("ki-1", V1)

    assert caught.value.details == {"item_id": "ki-1", "version_tag": "v1"}


def test_review_flag_reads_back_when_saved(repository: PostgresExtractedContentRepository):
    flagged = ExtractedContent(
        document_format=DocumentFormat.PDF,
        page_count=1,
        blocks=(
            ContentBlock.table(
                order=0,
                rows=[["a", "b"]],
                page_number=1,
                source=ContentSource.LVM,
                review_reason="OCR disagrees.",
            ),
        ),
    )

    repository.save("ki-1", V1, flagged)

    assert repository.get("ki-1", V1) == flagged


def test_content_is_stored_again_when_schema_is_rebuilt_by_migrations(
    postgres_url: str, database: PostgresDatabase
):
    migrate(postgres_url, "base", downgrade=True)
    migrate(postgres_url)
    repository = PostgresExtractedContentRepository(database)

    repository.save("ki-1", V1, CONTENT)

    assert repository.get("ki-1", V1) == CONTENT
