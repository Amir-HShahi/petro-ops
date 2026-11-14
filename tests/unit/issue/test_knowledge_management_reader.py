import pytest

from offline_rag.issue.infrastructure.knowledge_management_reader import page_or_section
from offline_rag.knowledge.domain.source_reference import SourceReference
from offline_rag.knowledge.domain.version_tag import VersionTag


@pytest.mark.parametrize(
    ("pages", "headings", "expected"),
    [
        ((4, 4), (), "p. 4"),
        ((4, None), (), "p. 4"),
        ((4, 6), (), "pp. 4-6"),
        ((None, None), ("4. Recommendation", "Riser R-3"), "4. Recommendation > Riser R-3"),
        ((None, None), (), ""),
    ],
)
def test_place_is_pages_or_headings_when_a_chunk_is_read(
    pages: tuple[int | None, int | None], headings: tuple[str, ...], expected: str
):
    reference = SourceReference(
        item_id="ins-02-v2",
        version_tag=VersionTag("v1"),
        heading_path=headings,
        page_start=pages[0],
        page_end=pages[1],
    )

    assert page_or_section(reference) == expected
