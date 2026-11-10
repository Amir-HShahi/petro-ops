"""Where a piece of knowledge came from, down to its section and pages (spec §7.4)."""

from dataclasses import dataclass

from offline_rag.knowledge.domain.version_tag import VersionTag


@dataclass(frozen=True, kw_only=True, slots=True)
class SourceReference:
    """The KnowledgeVersion, section and pages a KnowledgeChunk was cut from (spec §7.4).

    An answer cites this, so a reader can open the exact version and find the text.

    Attributes:
        item_id: The KnowledgeItem.
        version_tag: The version of the item. A chunk never moves to another version.
        heading_path: Headings above the text, outermost first. Empty for PDF files,
            whose headings stay in the page text.
        page_start: First page the text is on, starting at 1. None for DOC and DOCX.
        page_end: Last page the text is on. None for DOC and DOCX.
    """

    item_id: str
    version_tag: VersionTag
    heading_path: tuple[str, ...] = ()
    page_start: int | None = None
    page_end: int | None = None
