"""The rules that cut extracted content into KnowledgeChunks (spec §7.4, ADR 0009).

1. A chunk never crosses a heading: a new heading path starts a new chunk.
2. Blocks of one section are packed in reading order until the next one would
   pass the target size.
3. No chunk passes the hard limit. A longer paragraph is cut at line breaks,
   then sentences, then words, and only as a last resort inside a word.
4. A table is kept whole when it fits. A longer one is cut between rows, and
   each part repeats the header row so its columns can still be read.
5. A chunk may start with the last sentences of the chunk before it, but only
   inside the same section and never from a table.

The same content and settings always give the same chunks.
"""

import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from itertools import groupby

from offline_rag.knowledge.domain.extracted_content import (
    TABLE_CELL_SEPARATOR,
    ContentBlock,
    ContentBlockKind,
    ExtractedContent,
)
from offline_rag.knowledge.domain.knowledge_chunk import KnowledgeChunk, chunk_id_for
from offline_rag.knowledge.domain.source_reference import SourceReference
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.shared_kernel.metadata_record import MetadataRecord

CountTokens = Callable[[str], int]

PIECE_SEPARATOR = "\n"

# Finer and finer places to cut text that is too long: lines, sentences, words.
# The Persian question mark ends a sentence too.
_CUT_LEVELS = (
    (re.compile(r"\n+"), "\n"),
    (re.compile(r"(?<=[.!?؟])\s+"), " "),
    (re.compile(r"\s+"), " "),
)


@dataclass(frozen=True, slots=True)
class _Piece:
    """Text that goes into a chunk whole, and the block it came from."""

    text: str
    block: ContentBlock


def chunk_content(
    content: ExtractedContent,
    *,
    item_id: str,
    version_tag: VersionTag,
    metadata: MetadataRecord,
    count_tokens: CountTokens,
    target_tokens: int,
    max_tokens: int,
    overlap_share: float,
) -> tuple[KnowledgeChunk, ...]:
    """Return the chunks of one KnowledgeVersion, in reading order.

    Args:
        content: What was extracted from the version.
        item_id: The KnowledgeItem the version belongs to.
        version_tag: The version.
        metadata: The version's metadata, copied into every chunk.
        count_tokens: Counts the tokens of a text.
        target_tokens: The size a chunk grows to before a new one starts.
        max_tokens: The size no chunk may pass. At least `target_tokens`.
        overlap_share: Share of a chunk, from 0 to 0.5, repeated at the start of
            the next chunk in the same section.
    """
    chunks: list[KnowledgeChunk] = []
    for heading_path, section_blocks in groupby(content.blocks, key=lambda b: b.heading_path):
        pieces = [
            piece
            for block in section_blocks
            for piece in _pieces(block, count_tokens, target_tokens, max_tokens)
        ]
        for chunk_pieces in _pack(
            pieces,
            count_tokens=count_tokens,
            target_tokens=target_tokens,
            max_tokens=max_tokens,
            overlap_share=overlap_share,
        ):
            text = _join(chunk_pieces)
            blocks = [piece.block for piece in chunk_pieces]
            pages = [block.page_number for block in blocks if block.page_number is not None]
            order = len(chunks)
            chunks.append(
                KnowledgeChunk(
                    chunk_id=chunk_id_for(item_id, version_tag, order),
                    source_reference=SourceReference(
                        item_id=item_id,
                        version_tag=version_tag,
                        heading_path=heading_path,
                        page_start=min(pages, default=None),
                        page_end=max(pages, default=None),
                    ),
                    order=order,
                    text=text,
                    token_count=count_tokens(text),
                    first_block_order=min(block.order for block in blocks),
                    last_block_order=max(block.order for block in blocks),
                    metadata=metadata,
                )
            )
    return tuple(chunks)


def _pieces(
    block: ContentBlock, count_tokens: CountTokens, target_tokens: int, max_tokens: int
) -> list[_Piece]:
    if count_tokens(block.text) <= max_tokens:
        return [_Piece(block.text, block)]
    if block.kind == ContentBlockKind.TABLE:
        return [_Piece(text, block) for text in _table_parts(block, count_tokens, max_tokens)]
    return [_Piece(text, block) for text in _cut_to_fit(block.text, count_tokens, target_tokens)]


def _table_parts(block: ContentBlock, count_tokens: CountTokens, max_tokens: int) -> list[str]:
    header, *rows = (TABLE_CELL_SEPARATOR.join(row) for row in block.table_rows)
    if not rows or count_tokens(header) >= max_tokens:
        return _cut_to_fit(block.text, count_tokens, max_tokens)

    parts: list[str] = []
    current: list[str] = []
    for row in rows:
        candidate = PIECE_SEPARATOR.join([header, *current, row])
        if count_tokens(candidate) <= max_tokens:
            current.append(row)
            continue
        if current:
            parts.append(PIECE_SEPARATOR.join([header, *current]))
            current = []
        lone_row = PIECE_SEPARATOR.join([header, row])
        if count_tokens(lone_row) <= max_tokens:
            current = [row]
        else:
            # One row longer than a chunk can only be cut inside the row.
            parts.extend(_cut_to_fit(lone_row, count_tokens, max_tokens))
    if current:
        parts.append(PIECE_SEPARATOR.join([header, *current]))
    return parts


def _cut_to_fit(text: str, count_tokens: CountTokens, limit: int, level: int = 0) -> list[str]:
    """Cut text into parts of at most `limit` tokens, as coarsely as possible."""
    if count_tokens(text) <= limit:
        return [text]
    if level == len(_CUT_LEVELS):
        return _cut_characters(text, count_tokens, limit)
    pattern, separator = _CUT_LEVELS[level]
    parts = [part for part in pattern.split(text) if part]
    if len(parts) <= 1:
        return _cut_to_fit(text, count_tokens, limit, level + 1)

    fitted: list[str] = []
    current = ""
    for part in parts:
        for small in _cut_to_fit(part, count_tokens, limit, level + 1):
            candidate = f"{current}{separator}{small}" if current else small
            if count_tokens(candidate) <= limit:
                current = candidate
            else:
                fitted.append(current)
                current = small
    fitted.append(current)
    return [part for part in fitted if part]


def _cut_characters(text: str, count_tokens: CountTokens, limit: int) -> list[str]:
    parts: list[str] = []
    while text:
        # The longest prefix that fits, found by halving; at least one character.
        low, high = 1, len(text)
        while low < high:
            middle = (low + high + 1) // 2
            if count_tokens(text[:middle]) <= limit:
                low = middle
            else:
                high = middle - 1
        parts.append(text[:low])
        text = text[low:]
    return parts


def _pack(
    pieces: Sequence[_Piece],
    *,
    count_tokens: CountTokens,
    target_tokens: int,
    max_tokens: int,
    overlap_share: float,
) -> Iterator[list[_Piece]]:
    overlap: _Piece | None = None
    current: list[_Piece] = []
    for piece in pieces:
        if current and count_tokens(_join([*current, piece])) > target_tokens:
            yield current
            overlap = _overlap(current, count_tokens, overlap_share)
            current = []
        if not current and overlap is not None:
            overlap = _trim_overlap(overlap, piece, count_tokens, max_tokens)
            current = [overlap] if overlap is not None else []
        current.append(piece)
    if current:
        yield current


def _overlap(
    chunk_pieces: list[_Piece], count_tokens: CountTokens, overlap_share: float
) -> _Piece | None:
    last = chunk_pieces[-1]
    budget = int(overlap_share * count_tokens(_join(chunk_pieces)))
    if budget < 1 or last.block.kind == ContentBlockKind.TABLE:
        return None
    # Whole sentences read better than a cut one, so they are tried first.
    for pattern, separator in _CUT_LEVELS[1:]:
        tail = _tail(pattern.split(last.text), separator, count_tokens, budget)
        if tail:
            return _Piece(tail, last.block)
    return None


def _tail(parts: list[str], separator: str, count_tokens: CountTokens, budget: int) -> str:
    tail = ""
    # The whole text is never repeated, only part of its end.
    for part in reversed(parts[1:]):
        candidate = f"{part}{separator}{tail}" if tail else part
        if count_tokens(candidate) > budget:
            break
        tail = candidate
    return tail


def _trim_overlap(
    overlap: _Piece, first_piece: _Piece, count_tokens: CountTokens, max_tokens: int
) -> _Piece | None:
    words = overlap.text.split(" ")
    while words:
        candidate = _Piece(" ".join(words), overlap.block)
        if count_tokens(_join([candidate, first_piece])) <= max_tokens:
            return candidate
        words = words[1:]
    return None


def _join(pieces: Sequence[_Piece]) -> str:
    return PIECE_SEPARATOR.join(piece.text for piece in pieces)
