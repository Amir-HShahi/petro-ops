"""KnowledgeChunk: a retrievable piece of one KnowledgeVersion (spec §7.4)."""

from dataclasses import dataclass

from offline_rag.knowledge.domain.source_reference import SourceReference
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.shared_kernel.metadata_record import MetadataRecord


def chunk_id_for(item_id: str, version_tag: VersionTag, order: int) -> str:
    """Return the id of a chunk. Chunking a version again gives the same ids."""
    return f"{item_id}/{version_tag.value}/{order}"


@dataclass(frozen=True, kw_only=True, slots=True)
class KnowledgeChunk:
    """A piece of one KnowledgeVersion, small enough to embed and cite (spec §7.4).

    A chunk belongs to exactly one version and never changes. Whether it can be
    retrieved is not stored: it follows from whether its version is the item's
    active one (spec §7.6), so publishing a new version supersedes the old chunks
    without touching them.

    Attributes:
        chunk_id: Stable id, built from the version and the order.
        source_reference: The item, version, headings and pages the text came from.
        order: Position within the version, starting at 0.
        text: The text to embed. It may start with the end of the chunk before it
            in the same section, so a sentence cut at the boundary is not lost.
        token_count: Tokens in `text`, as the tokenizer counted them.
        first_block_order: The first `ContentBlock` the text came from.
        last_block_order: The last `ContentBlock` the text came from.
        metadata: The metadata of the version, copied so retrieval can filter on it.
    """

    chunk_id: str
    source_reference: SourceReference
    order: int
    text: str
    token_count: int
    first_block_order: int
    last_block_order: int
    metadata: MetadataRecord

    def is_retrievable(self, active_version_tag: VersionTag) -> bool:
        """Return whether retrieval may use the chunk: only while its version is active.

        Args:
            active_version_tag: The active version of the chunk's KnowledgeItem.
        """
        return self.source_reference.version_tag == active_version_tag
