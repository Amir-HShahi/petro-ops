"""The words of an Issue's text, for comparing it with other Issues (ADR 0012).

Issue texts are a title and a few sentences, so they are compared as sets of words
rather than as the long shingles used for documents (ADR 0010). Equipment tags such
as `R-3` or `P-4101A` stay one word, because they tell two similar problems apart.
"""

import re
import unicodedata

# Arabic letters Persian text often carries by mistake, and Persian and Arabic digits.
# The same unification as for documents, so a tag typed with Persian digits matches.
_UNIFIED_CHARACTERS = str.maketrans(
    {
        "ي": "ی",
        "ى": "ی",
        "ك": "ک",
        **{chr(0x06F0 + digit): str(digit) for digit in range(10)},
        **{chr(0x0660 + digit): str(digit) for digit in range(10)},
    }
)
# A run of letters and digits, joined by single hyphens: `riser`, `r-3`, `p-4101a`.
_WORD = re.compile(r"[^\W_]+(?:-[^\W_]+)*")
_DIGIT = re.compile(r"\d")
_LETTER = re.compile(r"[^\W\d_]")

# Words that carry no subject. Kept short on purpose: a missed stop word only adds
# a little noise, while a wrongly dropped word hides a real match.
_ENGLISH_STOP_WORDS = (
    "a an the and or but of in on at to for from by with without as than then into "
    "over under about after before since while where which who whom whose what when "
    "is are was were be been being has have had do does did it its this that these "
    "those not no so also now only more most less very can could should would will"
)
_PERSIAN_STOP_WORDS = "و در به از که این آن را با برای است هست بود شد شده شود می یک تا هم یا اما"
_STOP_WORDS = frozenset(f"{_ENGLISH_STOP_WORDS} {_PERSIAN_STOP_WORDS}".split())


def issue_words(title: str, description: str) -> frozenset[str]:
    """Return the distinct words of an Issue's title and description, without stop words.

    The text is NFKC-normalized and lower-cased, with Arabic letters and Persian
    digits unified.
    """
    text = unicodedata.normalize("NFKC", f"{title} {description}")
    text = text.casefold().translate(_UNIFIED_CHARACTERS)
    return frozenset(word for word in _WORD.findall(text) if word not in _STOP_WORDS)


def equipment_tags(words: frozenset[str]) -> frozenset[str]:
    """Return the words that hold both a letter and a digit, such as `r-3` or `p-4101a`.

    Plain numbers such as years and measurements are not tags.
    """
    return frozenset(word for word in words if _DIGIT.search(word) and _LETTER.search(word))


def word_similarity(first: frozenset[str], second: frozenset[str]) -> float:
    """Return the Dice similarity of two word sets, from 0 (no word shared) to 1 (the same)."""
    if not first or not second:
        return 0.0
    return 2 * len(first & second) / (len(first) + len(second))


def names_other_equipment(first: frozenset[str], second: frozenset[str]) -> bool:
    """Return whether each text names an equipment tag the other does not.

    Two Issues about `riser R-2` and `riser R-3` share most of their words, but are
    about different equipment. When only one text names an extra tag, the other may
    simply leave it out, so that does not count.
    """
    first_tags, second_tags = equipment_tags(first), equipment_tags(second)
    return bool(first_tags - second_tags) and bool(second_tags - first_tags)
