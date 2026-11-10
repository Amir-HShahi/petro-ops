import math

from hypothesis import given, settings
from hypothesis import strategies as st

from offline_rag.knowledge.domain.chunking import chunk_content
from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.extracted_content import (
    TABLE_CELL_SEPARATOR,
    ContentBlock,
    ExtractedContent,
)
from offline_rag.knowledge.domain.knowledge_chunk import KnowledgeChunk
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.shared_kernel.metadata_record import MetadataRecord

V1 = VersionTag("v1")
METADATA = MetadataRecord(document_type="inspection_report")
SCOPE = ("Ultrasonic Wall Thickness Survey", "1. Scope")
FINDINGS = ("Ultrasonic Wall Thickness Survey", "3. Findings")


def _count(text: str) -> int:
    return math.ceil(len(text) / 4)


def _docx(*blocks: ContentBlock) -> ExtractedContent:
    return ExtractedContent(document_format=DocumentFormat.DOCX, page_count=None, blocks=blocks)


def _chunk(
    content: ExtractedContent,
    *,
    target_tokens: int = 50,
    max_tokens: int = 60,
    overlap_share: float = 0.0,
) -> tuple[KnowledgeChunk, ...]:
    return chunk_content(
        content,
        item_id="ki-1",
        version_tag=V1,
        metadata=METADATA,
        count_tokens=_count,
        target_tokens=target_tokens,
        max_tokens=max_tokens,
        overlap_share=overlap_share,
    )


def _sentence(number: int) -> str:
    return f"Reading {number} at the splash zone shows local wall loss."


def test_no_chunks_are_made_when_content_is_empty():
    assert _chunk(_docx()) == ()


def test_small_section_becomes_one_chunk_with_its_source_when_it_fits():
    content = _docx(ContentBlock.paragraph(order=0, text="Repeat UT survey.", heading_path=SCOPE))

    (chunk,) = _chunk(content)

    assert chunk.chunk_id == "ki-1/v1/0"
    assert chunk.text == "Repeat UT survey."
    assert chunk.token_count == _count("Repeat UT survey.")
    assert chunk.source_reference.heading_path == SCOPE
    assert (chunk.first_block_order, chunk.last_block_order) == (0, 0)
    assert chunk.metadata == METADATA


def test_new_chunk_starts_when_the_heading_path_changes():
    content = _docx(
        ContentBlock.paragraph(order=0, text="Repeat UT survey.", heading_path=SCOPE),
        ContentBlock.paragraph(order=1, text="Wall loss is local.", heading_path=FINDINGS),
    )

    chunks = _chunk(content, target_tokens=400, max_tokens=512)

    assert [chunk.source_reference.heading_path for chunk in chunks] == [SCOPE, FINDINGS]
    assert [chunk.order for chunk in chunks] == [0, 1]


def test_blocks_of_one_section_are_packed_together_when_they_fit_the_target():
    content = _docx(
        ContentBlock.paragraph(order=0, text="First note.", heading_path=SCOPE),
        ContentBlock.paragraph(order=1, text="Second note.", heading_path=SCOPE),
    )

    (chunk,) = _chunk(content)

    assert chunk.text == "First note.\nSecond note."
    assert (chunk.first_block_order, chunk.last_block_order) == (0, 1)


def test_long_paragraph_is_cut_at_sentence_ends_when_it_passes_the_hard_limit():
    text = " ".join(_sentence(number) for number in range(12))
    content = _docx(ContentBlock.paragraph(order=0, text=text, heading_path=FINDINGS))

    chunks = _chunk(content)

    assert len(chunks) > 1
    assert all(chunk.token_count <= 60 for chunk in chunks)
    assert all(chunk.text.endswith(".") for chunk in chunks)
    assert " ".join(chunk.text for chunk in chunks) == text


def test_table_is_kept_whole_when_it_fits_the_hard_limit():
    rows = [["Location", "Measured (mm)"], ["EL +8.5 m", "18.9"], ["EL +5.0 m", "20.0"]]
    table = ContentBlock.table(order=0, rows=rows, heading_path=FINDINGS)

    (chunk,) = _chunk(_docx(table))

    assert chunk.text == table.text


def test_long_table_is_cut_between_rows_with_the_header_repeated_when_it_passes_the_limit():
    header = ["Location", "Nominal (mm)", "Measured (mm)"]
    rows = [header, *([f"R-3 EL +{number}.0 m, 6 o'clock", "22.2", "20.1"] for number in range(20))]
    table = ContentBlock.table(order=0, rows=rows, heading_path=FINDINGS)
    header_line = TABLE_CELL_SEPARATOR.join(header)

    chunks = _chunk(_docx(table))

    assert len(chunks) > 1
    assert all(chunk.text.split("\n")[0] == header_line for chunk in chunks)
    assert all(chunk.token_count <= 60 for chunk in chunks)
    data_rows = [line for chunk in chunks for line in chunk.text.split("\n")[1:]]
    assert data_rows == table.text.split("\n")[1:]


def test_next_chunk_repeats_the_end_of_the_previous_one_when_both_are_in_one_section():
    content = _docx(
        *(
            ContentBlock.paragraph(order=order, text=_sentence(order), heading_path=FINDINGS)
            for order in range(4)
        )
    )

    first, second, *_ = _chunk(content, target_tokens=30, max_tokens=40, overlap_share=0.5)

    repeated = second.text.split("\n")[0]
    assert repeated != first.text
    assert first.text.endswith(repeated)
    assert second.first_block_order == first.last_block_order


def test_nothing_is_repeated_across_a_heading_when_overlap_is_set():
    content = _docx(
        ContentBlock.paragraph(order=0, text=_sentence(0), heading_path=SCOPE),
        ContentBlock.paragraph(order=1, text=_sentence(1), heading_path=FINDINGS),
    )

    _, findings = _chunk(content, target_tokens=30, max_tokens=40, overlap_share=0.5)

    assert findings.text == _sentence(1)
    assert findings.first_block_order == 1


def test_chunk_covers_the_pages_of_its_blocks_when_content_is_a_pdf():
    content = ExtractedContent(
        document_format=DocumentFormat.PDF,
        page_count=3,
        blocks=(
            ContentBlock.paragraph(order=0, text="Page two note.", page_number=2),
            ContentBlock.paragraph(order=1, text="Page three note.", page_number=3),
        ),
    )

    (chunk,) = _chunk(content)

    assert (chunk.source_reference.page_start, chunk.source_reference.page_end) == (2, 3)


def test_pages_are_unknown_when_content_is_a_docx():
    (chunk,) = _chunk(_docx(ContentBlock.paragraph(order=0, text="Note.")))

    assert (chunk.source_reference.page_start, chunk.source_reference.page_end) == (None, None)


def test_same_content_gives_the_same_chunks_when_chunked_twice():
    text = " ".join(_sentence(number) for number in range(12))
    content = _docx(ContentBlock.paragraph(order=0, text=text, heading_path=FINDINGS))

    assert _chunk(content, overlap_share=0.2) == _chunk(content, overlap_share=0.2)


def test_chunk_is_retrievable_only_when_its_version_is_active():
    (chunk,) = _chunk(_docx(ContentBlock.paragraph(order=0, text="Note.")))

    assert chunk.is_retrievable(V1)
    assert not chunk.is_retrievable(VersionTag("v2"))


# Latin and Persian letters, digits and sentence ends.
_ALPHABET = "abcdefghijklmno0123456789.,!?" + "".join(map(chr, range(0x0627, 0x0630)))
_WORD = st.text(alphabet=_ALPHABET, min_size=1, max_size=30)
_TEXT = st.lists(_WORD, min_size=1, max_size=60).map(" ".join)
_HEADINGS = st.sampled_from([(), SCOPE, FINDINGS])


@st.composite
def _contents(draw: st.DrawFn) -> ExtractedContent:
    blocks: list[ContentBlock] = []
    for order in range(draw(st.integers(min_value=0, max_value=8))):
        heading_path = draw(_HEADINGS)
        if draw(st.booleans()):
            blocks.append(
                ContentBlock.paragraph(
                    order=order,
                    text=draw(_TEXT.filter(lambda text: text.strip())),
                    heading_path=heading_path,
                )
            )
        else:
            columns = draw(st.integers(min_value=1, max_value=4))
            rows = draw(
                st.lists(
                    st.lists(_WORD, min_size=columns, max_size=columns), min_size=1, max_size=25
                )
            )
            blocks.append(ContentBlock.table(order=order, rows=rows, heading_path=heading_path))
    return _docx(*blocks)


@settings(max_examples=200, deadline=None)
@given(
    content=_contents(),
    target_tokens=st.integers(min_value=1, max_value=80),
    extra_tokens=st.integers(min_value=0, max_value=40),
    overlap_share=st.floats(min_value=0, max_value=0.5),
)
def test_no_chunk_passes_the_hard_limit_when_content_and_sizes_vary(
    content: ExtractedContent, target_tokens: int, extra_tokens: int, overlap_share: float
):
    max_tokens = target_tokens + extra_tokens

    chunks = _chunk(
        content, target_tokens=target_tokens, max_tokens=max_tokens, overlap_share=overlap_share
    )

    assert all(0 < chunk.token_count <= max_tokens for chunk in chunks)
    assert all(chunk.token_count == _count(chunk.text) for chunk in chunks)
    assert [chunk.order for chunk in chunks] == list(range(len(chunks)))
    assert bool(chunks) == bool(content.blocks)
