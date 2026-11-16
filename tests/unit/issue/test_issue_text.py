import pytest

from offline_rag.issue.domain.issue_text import (
    equipment_tags,
    issue_words,
    names_other_equipment,
    word_similarity,
)


def test_words_are_normalized_without_stop_words_when_read():
    words = issue_words("Riser R-3 Splash Zone", "The coating has FAILED, and the wall is thin.")

    assert words == frozenset(
        {"riser", "r-3", "splash", "zone", "coating", "failed", "wall", "thin"}
    )


def test_persian_letters_and_digits_are_unified_when_read():
    assert issue_words("خوردگی رایزر R-۳", "") == issue_words("خوردگي رايزر R-3", "")


def test_persian_stop_words_are_dropped_when_read():
    assert issue_words("خوردگی در رایزر", "و پوشش") == frozenset({"خوردگی", "رایزر", "پوشش"})


@pytest.mark.parametrize(
    ("text", "tags"),
    [
        ("pump P-4101A tripped in 2026", {"p-4101a"}),
        ("riser R-3 on SP-12 at 5.5 mm/s", {"r-3", "sp-12"}),
        ("no tags here, only 1.4 years", set()),
    ],
)
def test_equipment_tags_hold_a_letter_and_a_digit_when_found(text: str, tags: set[str]):
    assert equipment_tags(issue_words(text, "")) == tags


@pytest.mark.parametrize(
    ("first", "second", "similarity"),
    [
        ({"riser", "r-3"}, {"riser", "r-3"}, 1.0),
        ({"riser", "r-3"}, {"pump", "p-4101a"}, 0.0),
        ({"riser", "r-3", "coating", "wall"}, {"riser", "r-3"}, 4 / 6),
        (set(), {"riser"}, 0.0),
    ],
)
def test_similarity_is_the_dice_score_when_two_word_sets_are_compared(
    first: set[str], second: set[str], similarity: float
):
    assert word_similarity(frozenset(first), frozenset(second)) == pytest.approx(similarity)


@pytest.mark.parametrize(
    ("first", "second", "is_other"),
    [
        ("riser R-2 coating", "riser R-3 coating", True),
        ("riser R-3 on SP-12", "riser R-3", False),
        ("riser coating", "riser R-3 coating", False),
        ("riser R-3", "riser R-3", False),
    ],
)
def test_other_equipment_is_named_only_when_each_text_has_its_own_tag(
    first: str, second: str, is_other: bool
):
    assert names_other_equipment(issue_words(first, ""), issue_words(second, "")) is is_other
