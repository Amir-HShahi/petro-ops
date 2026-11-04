import pytest
from hypothesis import given
from hypothesis import strategies as st

from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.errors import InvalidExtractedContentError
from offline_rag.knowledge.domain.extracted_content import (
    ContentBlock,
    ContentBlockKind,
    ContentSource,
    ExtractedContent,
    normalize_extracted_text,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("retro\ufb01t", "retrofit"),
        ("wall\u00a0loss  of\t2.1 mm", "wall loss of 2.1 mm"),
        ("  first line  \n\n\n  second line ", "first line\nsecond line"),
        ("\uff25\uff2c +8.5 m", "EL +8.5 m"),
    ],
)
def test_text_is_normalized_when_extracted(raw: str, expected: str):
    assert normalize_extracted_text(raw) == expected


@given(text=st.text())
def test_normalizing_twice_changes_nothing_when_text_is_already_normalized(text: str):
    once = normalize_extracted_text(text)

    assert normalize_extracted_text(once) == once


def test_table_block_joins_cells_like_the_golden_set_when_built():
    block = ContentBlock.table(
        order=0,
        rows=[["Location", "Measured (mm)"], ["R-3 EL +8.5 m,\n6 o'clock", " 20.1 "]],
        heading_path=("2. Readings",),
    )

    assert block.kind == ContentBlockKind.TABLE
    assert block.table_rows == (("Location", "Measured (mm)"), ("R-3 EL +8.5 m, 6 o'clock", "20.1"))
    assert block.text == "Location | Measured (mm)\nR-3 EL +8.5 m, 6 o'clock | 20.1"


def test_paragraph_block_normalizes_text_and_headings_when_built():
    block = ContentBlock.paragraph(order=0, text=" Scope  text ", heading_path=(" 1.  Scope ",))

    assert block.text == "Scope text"
    assert block.heading_path == ("1. Scope",)
    assert block.table_rows == ()


def _pdf(*blocks: ContentBlock, page_count: int = 2) -> ExtractedContent:
    return ExtractedContent(
        document_format=DocumentFormat.PDF, page_count=page_count, blocks=blocks
    )


def test_pages_with_little_text_are_listed_when_text_layer_is_missing():
    content = _pdf(
        ContentBlock.paragraph(
            order=0, text="A full page of riser inspection text.", page_number=1
        ),
        ContentBlock.paragraph(order=1, text="3", page_number=2),
        page_count=3,
    )

    assert content.pages_without_text(min_page_text_chars=20) == (2, 3)


def test_spaces_do_not_count_when_pages_are_measured():
    content = _pdf(ContentBlock.paragraph(order=0, text="a b c d e", page_number=1), page_count=1)

    assert content.pages_without_text(min_page_text_chars=6) == (1,)
    assert content.pages_without_text(min_page_text_chars=5) == ()


def test_docx_has_no_pages_without_text_when_it_has_no_pages():
    content = ExtractedContent(document_format=DocumentFormat.DOCX, page_count=None, blocks=())

    assert content.pages_without_text(min_page_text_chars=20) == ()


@pytest.mark.parametrize(
    ("document_format", "page_count", "blocks", "reason"),
    [
        (
            DocumentFormat.DOCX,
            None,
            (ContentBlock.paragraph(order=1, text="x"),),
            "do not run 0, 1, 2",
        ),
        (DocumentFormat.PDF, None, (), "needs a page count"),
        (DocumentFormat.PDF, 0, (), "needs a page count"),
        (DocumentFormat.DOCX, 2, (), "has no pages"),
        (DocumentFormat.DOCX, None, (ContentBlock.paragraph(order=0, text="  "),), "is empty"),
        (
            DocumentFormat.DOCX,
            None,
            (ContentBlock(order=0, kind=ContentBlockKind.TABLE, text="x"),),
            "if and only if it is a table",
        ),
        (
            DocumentFormat.DOCX,
            None,
            (ContentBlock.paragraph(order=0, text="x", page_number=1),),
            "has a page number",
        ),
        (
            DocumentFormat.PDF,
            1,
            (ContentBlock.paragraph(order=0, text="x", page_number=2),),
            "not on a page",
        ),
        (DocumentFormat.PDF, 1, (ContentBlock.paragraph(order=0, text="x"),), "not on a page"),
    ],
)
def test_content_is_rejected_when_it_breaks_a_rule(
    document_format: DocumentFormat,
    page_count: int | None,
    blocks: tuple[ContentBlock, ...],
    reason: str,
):
    with pytest.raises(InvalidExtractedContentError, match=reason) as caught:
        ExtractedContent(document_format=document_format, page_count=page_count, blocks=blocks)

    assert caught.value.code == "KNOWLEDGE_INVALID_EXTRACTED_CONTENT"


def test_given_pages_get_new_blocks_and_others_keep_theirs_when_pages_are_replaced():
    content = _pdf(
        ContentBlock.paragraph(order=0, text="Page one text layer.", page_number=1),
        ContentBlock.paragraph(order=1, text="Page three text layer.", page_number=3),
        page_count=3,
    )
    lvm_blocks = [
        ContentBlock.paragraph(
            order=0, text="Read from the scan.", page_number=2, source=ContentSource.LVM
        ),
        ContentBlock.table(order=0, rows=[["a", "b"]], page_number=2, source=ContentSource.LVM),
    ]

    replaced = content.with_page_blocks({2: lvm_blocks})

    assert [(block.order, block.page_number) for block in replaced.blocks] == [
        (0, 1),
        (1, 2),
        (2, 2),
        (3, 3),
    ]
    assert [block.source for block in replaced.blocks if block.page_number == 2] == [
        ContentSource.LVM
    ] * 2


def test_old_blocks_of_a_page_are_dropped_when_the_page_is_read_again():
    content = _pdf(
        ContentBlock.paragraph(order=0, text="First reading.", page_number=1), page_count=1
    )

    replaced = content.with_page_blocks(
        {1: [ContentBlock.paragraph(order=0, text="Second reading.", page_number=1)]}
    )

    assert [block.text for block in replaced.blocks] == ["Second reading."]


def test_table_is_marked_for_review_when_built_with_a_reason():
    block = ContentBlock.table(order=0, rows=[["a"]], review_reason="OCR disagrees.")

    assert block.needs_human_review
    assert block.review_reason == "OCR disagrees."


@pytest.mark.parametrize(("needs_review", "reason"), [(True, None), (False, "a reason")])
def test_content_is_rejected_when_review_flag_and_reason_disagree(
    needs_review: bool, reason: str | None
):
    block = ContentBlock(
        order=0,
        kind=ContentBlockKind.TEXT,
        text="x",
        needs_human_review=needs_review,
        review_reason=reason,
    )

    with pytest.raises(InvalidExtractedContentError, match="review reason"):
        ExtractedContent(document_format=DocumentFormat.DOCX, page_count=None, blocks=(block,))
