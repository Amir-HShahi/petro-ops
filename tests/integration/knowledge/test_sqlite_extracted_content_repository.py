import sqlite3
from pathlib import Path

import pytest

from offline_rag.knowledge.application.errors import ExtractedContentNotFoundError
from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.extracted_content import (
    ContentBlock,
    ContentSource,
    ExtractedContent,
)
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.knowledge.infrastructure.sqlite_extracted_content_repository import (
    SqliteExtractedContentRepository,
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
def repository(tmp_path: Path) -> SqliteExtractedContentRepository:
    return SqliteExtractedContentRepository(tmp_path / "knowledge.sqlite3")


def test_content_reads_back_unchanged_when_saved(repository: SqliteExtractedContentRepository):
    repository.save("ki-1", V1, CONTENT)

    assert repository.get("ki-1", V1) == CONTENT


def test_old_blocks_are_replaced_when_version_is_saved_again(
    repository: SqliteExtractedContentRepository,
):
    repository.save("ki-1", V1, CONTENT)
    newer = ExtractedContent(
        document_format=DocumentFormat.PDF,
        page_count=1,
        blocks=(ContentBlock.paragraph(order=0, text="Only one block now.", page_number=1),),
    )

    repository.save("ki-1", V1, newer)

    assert repository.get("ki-1", V1) == newer


def test_versions_are_kept_apart_when_both_are_saved(repository: SqliteExtractedContentRepository):
    repository.save("ki-1", V1, CONTENT)
    empty_docx = ExtractedContent(document_format=DocumentFormat.DOCX, page_count=None, blocks=())

    repository.save("ki-1", VersionTag("v2"), empty_docx)

    assert repository.get("ki-1", V1) == CONTENT
    assert repository.get("ki-1", VersionTag("v2")) == empty_docx


def test_lookup_raises_not_found_when_nothing_was_extracted(
    repository: SqliteExtractedContentRepository,
):
    with pytest.raises(ExtractedContentNotFoundError) as caught:
        repository.get("ki-1", V1)

    assert caught.value.details == {"item_id": "ki-1", "version_tag": "v1"}


def test_review_flag_reads_back_when_saved(repository: SqliteExtractedContentRepository):
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


def test_old_database_gets_the_review_columns_when_opened(tmp_path: Path):
    database_path = tmp_path / "knowledge.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE extracted_contents (
                item_id TEXT NOT NULL, version_tag TEXT NOT NULL, document_format TEXT NOT NULL,
                page_count INTEGER, PRIMARY KEY (item_id, version_tag));
            CREATE TABLE content_blocks (
                item_id TEXT NOT NULL, version_tag TEXT NOT NULL, block_order INTEGER NOT NULL,
                kind TEXT NOT NULL, text TEXT NOT NULL, page_number INTEGER,
                heading_path_json TEXT NOT NULL, table_rows_json TEXT NOT NULL,
                source TEXT NOT NULL, PRIMARY KEY (item_id, version_tag, block_order));
            INSERT INTO extracted_contents VALUES ('ki-0', 'v1', 'docx', NULL);
            INSERT INTO content_blocks VALUES
                ('ki-0', 'v1', 0, 'text', 'Old row.', NULL, '[]', '[]', 'text_layer');
            """
        )

    repository = SqliteExtractedContentRepository(database_path)

    assert repository.get("ki-0", V1).blocks[0].needs_human_review is False
    repository.save("ki-1", V1, CONTENT)
    assert repository.get("ki-1", V1) == CONTENT
