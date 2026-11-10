"""Lexical fingerprints of extracted text, for near-duplicate and overlap checks (ADR 0010).

Text is compared after normalization, so the same words saved as DOCX and as PDF,
or typed with Arabic instead of Persian letters, give the same fingerprint.
"""

import hashlib
import re
import unicodedata
from collections.abc import Sequence

from offline_rag.knowledge.domain.extracted_content import ExtractedContent

Shingles = frozenset[str]

# Arabic letters Persian text often carries by mistake, and Persian and Arabic digits.
_UNIFIED_CHARACTERS = str.maketrans(
    {
        "ي": "ی",
        "ى": "ی",
        "ك": "ک",
        **{chr(0x06F0 + digit): str(digit) for digit in range(10)},
        **{chr(0x0660 + digit): str(digit) for digit in range(10)},
    }
)
_NOT_WORD = re.compile(r"[\W_]+")


def normalize_for_fingerprint(text: str) -> str:
    """Return the text as lower-case words split by single spaces, without punctuation."""
    text = unicodedata.normalize("NFKC", text).casefold().translate(_UNIFIED_CHARACTERS)
    return " ".join(_NOT_WORD.sub(" ", text).split())


def reading_text(content: ExtractedContent) -> str:
    """Return all text of a version in reading order, headings included.

    DOC and DOCX headings are kept in `heading_path`, not in blocks, while a PDF
    keeps them in the page text. Putting them back where they start lets the two
    formats of one document read the same.
    """
    lines: list[str] = []
    previous_path: tuple[str, ...] = ()
    for block in content.blocks:
        path = block.heading_path
        shared = next(
            (
                depth
                for depth, (a, b) in enumerate(zip(previous_path, path, strict=False))
                if a != b
            ),
            min(len(previous_path), len(path)),
        )
        lines.extend(path[shared:])
        lines.append(block.text)
        previous_path = path
    return "\n".join(lines)


def normalized_text_hash(text: str) -> str | None:
    """Return the SHA-256 of the normalized text, or None when it has no words."""
    normalized = normalize_for_fingerprint(text)
    return hashlib.sha256(normalized.encode()).hexdigest() if normalized else None


def word_shingles(text: str, *, words_per_shingle: int) -> Shingles:
    """Return every run of `words_per_shingle` words in the normalized text.

    Text shorter than that gives one shingle of all its words; text with no
    words gives none.
    """
    words = normalize_for_fingerprint(text).split()
    if len(words) <= words_per_shingle:
        return frozenset({" ".join(words)}) if words else frozenset()
    return frozenset(
        " ".join(words[start : start + words_per_shingle])
        for start in range(len(words) - words_per_shingle + 1)
    )


def shingle_containment(part: Shingles, whole: Shingles) -> float:
    """Return the share of `part`'s shingles that also occur in `whole`, from 0 to 1.

    Unlike a symmetric measure, a short paragraph copied into a long report still
    scores high, and chunk boundaries that fall in different places do not matter.
    An empty `part` scores 0.
    """
    return len(part & whole) / len(part) if part else 0.0


def chunk_containments(
    candidate_chunks: Sequence[Shingles], existing_version: Shingles
) -> tuple[float, ...]:
    """Return, for each candidate chunk, how much of it occurs in an existing version.

    Args:
        candidate_chunks: The shingles of each chunk of the version being checked.
        existing_version: All shingles of all chunks of the version compared with.
    """
    return tuple(shingle_containment(chunk, existing_version) for chunk in candidate_chunks)
