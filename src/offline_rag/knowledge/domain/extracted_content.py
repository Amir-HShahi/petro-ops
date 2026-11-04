"""Text and structure extracted from one KnowledgeVersion (spec §7.2 steps 3 and 4, §7.3)."""

import re
import unicodedata
from dataclasses import dataclass, field, replace
from enum import StrEnum

from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.errors import InvalidExtractedContentError

TABLE_CELL_SEPARATOR = " | "

_SPACES = re.compile(r"[^\S\n]+")
_BLANK_LINES = re.compile(r"\n\s*\n+")


def normalize_extracted_text(text: str) -> str:
    """Return text in the one form every extractor produces.

    NFKC turns ligatures and other compatibility characters into plain ones, so a
    PDF's "retroﬁt" matches "retrofit" (ADR 0002). Runs of spaces become one space,
    blank lines are removed and each line is trimmed.
    """
    text = unicodedata.normalize("NFKC", text)
    text = _BLANK_LINES.sub("\n", _SPACES.sub(" ", text))
    return "\n".join(line.strip() for line in text.split("\n")).strip()


class ContentBlockKind(StrEnum):
    """What a block holds."""

    TEXT = "text"
    TABLE = "table"


class ContentSource(StrEnum):
    """Where a block's text came from. Text from a model is trusted less (ADR 0002)."""

    TEXT_LAYER = "text_layer"
    LVM = "lvm"


@dataclass(frozen=True, kw_only=True, slots=True)
class ContentBlock:
    """One paragraph run or one table, with where it sits in the source file.

    Attributes:
        order: Position in the file, starting at 0.
        kind: Text or table.
        text: Normalized text. A table's rows are joined by newlines and its cells
            by `TABLE_CELL_SEPARATOR`, the form `fixtures/golden/` quotes use.
        page_number: Page, starting at 1, for PDF files. None for DOC and DOCX.
        heading_path: Headings above the block, outermost first, for DOC and DOCX.
        table_rows: The normalized cells of each row, for tables only.
        source: Where the text came from.
        needs_human_review: Whether a person must check the block before it is
            trusted, such as a scanned table the two models read differently.
        review_reason: Why the block needs review. Set exactly when it does.
    """

    order: int
    kind: ContentBlockKind
    text: str
    page_number: int | None = None
    heading_path: tuple[str, ...] = ()
    table_rows: tuple[tuple[str, ...], ...] = field(default=())
    source: ContentSource = ContentSource.TEXT_LAYER
    needs_human_review: bool = False
    review_reason: str | None = None

    @classmethod
    def paragraph(
        cls,
        *,
        order: int,
        text: str,
        page_number: int | None = None,
        heading_path: tuple[str, ...] = (),
        source: ContentSource = ContentSource.TEXT_LAYER,
    ) -> "ContentBlock":
        """Return a text block with its text normalized."""
        return cls(
            order=order,
            kind=ContentBlockKind.TEXT,
            text=normalize_extracted_text(text),
            page_number=page_number,
            heading_path=tuple(normalize_extracted_text(h) for h in heading_path),
            source=source,
        )

    @classmethod
    def table(
        cls,
        *,
        order: int,
        rows: list[list[str]],
        page_number: int | None = None,
        heading_path: tuple[str, ...] = (),
        source: ContentSource = ContentSource.TEXT_LAYER,
        review_reason: str | None = None,
    ) -> "ContentBlock":
        """Return a table block with each cell normalized onto one line.

        A `review_reason` marks the table for human review.
        """
        table_rows = tuple(
            tuple(normalize_extracted_text(cell).replace("\n", " ") for cell in row) for row in rows
        )
        return cls(
            order=order,
            kind=ContentBlockKind.TABLE,
            text="\n".join(TABLE_CELL_SEPARATOR.join(row) for row in table_rows),
            page_number=page_number,
            heading_path=tuple(normalize_extracted_text(h) for h in heading_path),
            table_rows=table_rows,
            source=source,
            needs_human_review=review_reason is not None,
            review_reason=review_reason,
        )


@dataclass(frozen=True, kw_only=True, slots=True)
class ExtractedContent:
    """All blocks extracted from one KnowledgeVersion, in reading order.

    Invariants:
    - Block orders run 0, 1, 2 without gaps.
    - No block is empty. A table has rows; a text block has none.
    - A PDF has a page count, and every block is on one of its pages. DOC and
      DOCX have neither, since they have no fixed pages.
    - A block has a review reason if and only if it needs human review.

    Attributes:
        document_format: Format of the file the blocks came from.
        page_count: Number of pages for a PDF. None for DOC and DOCX.
        blocks: The blocks, in reading order.
    """

    document_format: DocumentFormat
    page_count: int | None
    blocks: tuple[ContentBlock, ...]

    def __post_init__(self) -> None:
        broken_rule = _first_broken_rule(self)
        if broken_rule:
            raise InvalidExtractedContentError(broken_rule)

    def with_page_blocks(self, page_blocks: dict[int, list[ContentBlock]]) -> "ExtractedContent":
        """Return a copy where each given PDF page holds only the given blocks.

        Other pages keep their blocks. Blocks are put in page order, and orders are
        numbered again from 0, so the result follows the same invariants.
        """
        kept = [block for block in self.blocks if block.page_number not in page_blocks]
        added = [block for blocks in page_blocks.values() for block in blocks]
        ordered = sorted(kept + added, key=lambda block: block.page_number or 0)
        return replace(
            self,
            blocks=tuple(replace(block, order=order) for order, block in enumerate(ordered)),
        )

    def pages_without_text(self, *, min_page_text_chars: int) -> tuple[int, ...]:
        """Return the PDF pages whose text layer has fewer than `min_page_text_chars` characters.

        Such pages are scanned or drawn, so their content needs the LVM (ADR 0002).
        Spaces do not count. DOC and DOCX files have no such pages.
        """
        if self.page_count is None:
            return ()
        chars_by_page = dict.fromkeys(range(1, self.page_count + 1), 0)
        for block in self.blocks:
            if block.page_number is not None:
                chars_by_page[block.page_number] += sum(not c.isspace() for c in block.text)
        return tuple(page for page, chars in chars_by_page.items() if chars < min_page_text_chars)


def _first_broken_rule(content: ExtractedContent) -> str | None:
    orders = [block.order for block in content.blocks]
    if orders != list(range(len(content.blocks))):
        return f"block orders {orders} do not run 0, 1, 2."

    page_count = content.page_count
    if content.document_format == DocumentFormat.PDF:
        if page_count is None or page_count < 1:
            return "a PDF needs a page count of at least 1."
    elif page_count is not None:
        return f"a {content.document_format} file has no pages."

    for block in content.blocks:
        if not block.text:
            return f"block {block.order} is empty."
        if (block.kind == ContentBlockKind.TABLE) != bool(block.table_rows):
            return f"block {block.order} must have rows if and only if it is a table."
        if page_count is None and block.page_number is not None:
            return f"block {block.order} has a page number."
        if page_count is not None and not 1 <= (block.page_number or 0) <= page_count:
            return f"block {block.order} is not on a page of the PDF."
        if block.needs_human_review != (block.review_reason is not None):
            return f"block {block.order} must have a review reason if and only if it needs review."
    return None
