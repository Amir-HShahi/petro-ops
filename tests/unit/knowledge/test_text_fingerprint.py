from hypothesis import given
from hypothesis import strategies as st

from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.extracted_content import ContentBlock, ExtractedContent
from offline_rag.knowledge.domain.text_fingerprint import (
    chunk_containments,
    normalize_for_fingerprint,
    normalized_text_hash,
    reading_text,
    shingle_containment,
    word_shingles,
)


def test_case_punctuation_and_spaces_are_dropped_when_text_is_normalized():
    assert normalize_for_fingerprint("Wall  loss,\nRiser R-3!") == "wall loss riser r 3"


def test_arabic_letters_and_persian_digits_become_one_form_when_text_is_normalized():
    assert normalize_for_fingerprint("كاهش ضخامت ۱۸\u066b۹") == normalize_for_fingerprint(
        "کاهش ضخامت 18.9"
    )


def test_same_hash_is_given_when_texts_differ_only_in_layout():
    assert normalized_text_hash("Wall loss.\n\nRiser R-3") == normalized_text_hash(
        "wall LOSS riser r-3"
    )


def test_no_hash_is_given_when_text_has_no_words():
    assert normalized_text_hash(" .,;\n") is None


def test_headings_are_put_back_where_they_start_when_reading_text_is_built():
    content = ExtractedContent(
        document_format=DocumentFormat.DOCX,
        page_count=None,
        blocks=(
            ContentBlock.paragraph(order=0, text="Scope text.", heading_path=("Report", "Scope")),
            ContentBlock.paragraph(order=1, text="More scope.", heading_path=("Report", "Scope")),
            ContentBlock.paragraph(order=2, text="Findings.", heading_path=("Report", "Findings")),
        ),
    )

    assert reading_text(content) == "Report\nScope\nScope text.\nMore scope.\nFindings\nFindings."


def test_runs_of_words_are_returned_when_text_is_longer_than_a_shingle():
    assert word_shingles("a b c d", words_per_shingle=3) == frozenset({"a b c", "b c d"})


def test_one_shingle_of_all_words_is_returned_when_text_is_short():
    assert word_shingles("Riser R3", words_per_shingle=5) == frozenset({"riser r3"})


def test_no_shingles_are_returned_when_text_has_no_words():
    assert word_shingles("...", words_per_shingle=5) == frozenset()


def test_containment_is_the_share_of_the_part_found_in_the_whole():
    part = frozenset({"a", "b", "c", "d"})

    assert shingle_containment(part, frozenset({"a", "b", "x"})) == 0.5


def test_containment_is_zero_when_part_is_empty():
    assert shingle_containment(frozenset(), frozenset({"a"})) == 0.0


def test_each_chunk_gets_its_own_containment_when_compared_with_a_version():
    chunks = [frozenset({"a", "b"}), frozenset({"x"})]

    assert chunk_containments(chunks, frozenset({"a", "b", "c"})) == (1.0, 0.0)


@given(st.text(max_size=200), st.integers(min_value=1, max_value=12))
def test_text_is_fully_contained_in_itself_when_it_has_words(text: str, words_per_shingle: int):
    shingles = word_shingles(text, words_per_shingle=words_per_shingle)

    assert shingle_containment(shingles, shingles) == (1.0 if shingles else 0.0)
