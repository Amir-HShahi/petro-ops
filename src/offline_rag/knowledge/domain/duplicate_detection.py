"""The DuplicateDetector domain service and the flags it raises (spec §7.7, ADR 0010).

The detector only names duplicates. What happens to a flagged KnowledgeItem is
open question 6 in `docs/domain-model.md`; until it is answered both items are kept.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier


class DuplicateKind(StrEnum):
    """How a KnowledgeVersion repeats another KnowledgeItem (spec §7.7)."""

    EXACT = "exact"
    """The two files are byte for byte the same."""
    NEAR = "near"
    """The files differ, but their normalized text is the same."""
    METADATA_VARIANT = "metadata_variant"
    """The normalized text is the same, but the metadata recorded with it differs."""
    OVERLAP = "overlap"
    """Enough of the chunks repeat text of the other item."""


@dataclass(frozen=True, kw_only=True, slots=True)
class VersionFingerprint:
    """What the detector compares of one KnowledgeVersion.

    Attributes:
        item_id: The KnowledgeItem.
        version_tag: The version.
        owner_node_id: The Node that owns the item. Only items of one Node are compared.
        content_hash: SHA-256 of the file.
        normalized_text_hash: SHA-256 of the normalized text. None until the version
            has been chunked, or when it has no text.
        metadata: The metadata recorded with the version.
    """

    item_id: str
    version_tag: VersionTag
    owner_node_id: NodeIdentifier
    content_hash: str
    normalized_text_hash: str | None
    metadata: MetadataRecord


@dataclass(frozen=True, kw_only=True, slots=True)
class DuplicateComparison:
    """An existing version to compare with, and how much each candidate chunk repeats it.

    Attributes:
        existing: The version compared with.
        chunk_similarities: For each chunk of the candidate, the share of its text
            found in `existing`, from 0 to 1. Empty when no chunks are compared,
            such as at submission, before anything is chunked.
    """

    existing: VersionFingerprint
    chunk_similarities: tuple[float, ...] = ()


@dataclass(frozen=True, kw_only=True, slots=True)
class DuplicateFlag:
    """A KnowledgeVersion repeats an existing KnowledgeItem of the same Node (spec §7.7).

    A flag is a finding, not a decision: both items are kept.

    Attributes:
        item_id: The KnowledgeItem the flag is on.
        version_tag: Its version that repeats the other item.
        kind: How it repeats the other item.
        existing_item_id: The item it repeats.
        existing_version_tag: The version of that item it was compared with.
        score: 1 for exact, near and metadata variant flags. For an overlap, the
            share of chunks that repeat the other item, from 0 to 1.
        is_ambiguous: Whether the score is in the gray band, so a person, or later
            the LLM, must decide whether it is a real overlap (spec §7.7).
    """

    item_id: str
    version_tag: VersionTag
    kind: DuplicateKind
    existing_item_id: str
    existing_version_tag: VersionTag
    score: float
    is_ambiguous: bool = False


_RANK_BY_KIND = {
    DuplicateKind.EXACT: 0,
    DuplicateKind.NEAR: 1,
    DuplicateKind.METADATA_VARIANT: 1,
    DuplicateKind.OVERLAP: 2,
}


class DuplicateDetector:
    """Finds which existing KnowledgeItems of the same Node a version repeats.

    Rules (docs/domain-model.md, `DuplicateDetector`), strongest first:
    1. The same file hash is an exact duplicate.
    2. The same normalized text hash is a near duplicate, or a metadata variant
       when the metadata differs.
    3. When at least `min_chunk_share` of the chunks reach `overlap_chunk_similarity`,
       the version overlaps the other item.
    4. When that share is only reached from `ambiguous_from_similarity`, the
       overlap is flagged as ambiguous.

    A version is never compared with its own item, whose other versions are its
    history, nor with items of another Node. Each existing item gets at most one
    flag, the strongest. The service is pure: the similarities come in as data.
    """

    def __init__(
        self,
        *,
        overlap_chunk_similarity: float,
        ambiguous_from_similarity: float,
        min_chunk_share: float,
    ) -> None:
        """Create the detector.

        Args:
            overlap_chunk_similarity: Similarity, from 0 to 1, from which a chunk
                counts as repeating the other item.
            ambiguous_from_similarity: Lower similarity, from which a chunk counts
                towards an ambiguous overlap. Below `overlap_chunk_similarity`.
            min_chunk_share: Share of the chunks, from 0 to 1, that must repeat the
                other item for an overlap flag.
        """
        self._overlap_chunk_similarity = overlap_chunk_similarity
        self._ambiguous_from_similarity = ambiguous_from_similarity
        self._min_chunk_share = min_chunk_share

    def detect(
        self, candidate: VersionFingerprint, comparisons: Sequence[DuplicateComparison]
    ) -> tuple[DuplicateFlag, ...]:
        """Return the flags of the candidate, one per existing item, ordered by item id.

        An empty result means the candidate repeats none of the items compared.
        """
        strongest: dict[str, DuplicateFlag] = {}
        for comparison in comparisons:
            existing = comparison.existing
            if (
                existing.item_id == candidate.item_id
                or existing.owner_node_id != candidate.owner_node_id
            ):
                continue
            flag = self._flag(candidate, comparison)
            if flag is None:
                continue
            kept = strongest.get(existing.item_id)
            if kept is None or _strength(flag) < _strength(kept):
                strongest[existing.item_id] = flag
        return tuple(strongest[item_id] for item_id in sorted(strongest))

    def _flag(
        self, candidate: VersionFingerprint, comparison: DuplicateComparison
    ) -> DuplicateFlag | None:
        existing = comparison.existing

        def flag(kind: DuplicateKind, score: float, *, is_ambiguous: bool = False) -> DuplicateFlag:
            return DuplicateFlag(
                item_id=candidate.item_id,
                version_tag=candidate.version_tag,
                kind=kind,
                existing_item_id=existing.item_id,
                existing_version_tag=existing.version_tag,
                score=score,
                is_ambiguous=is_ambiguous,
            )

        if candidate.content_hash == existing.content_hash:
            return flag(DuplicateKind.EXACT, 1.0)
        if (
            candidate.normalized_text_hash is not None
            and candidate.normalized_text_hash == existing.normalized_text_hash
        ):
            if candidate.metadata != existing.metadata:
                return flag(DuplicateKind.METADATA_VARIANT, 1.0)
            return flag(DuplicateKind.NEAR, 1.0)

        similarities = comparison.chunk_similarities
        if not similarities:
            return None
        overlap_share = _share_at_least(similarities, self._overlap_chunk_similarity)
        if overlap_share >= self._min_chunk_share:
            return flag(DuplicateKind.OVERLAP, overlap_share)
        ambiguous_share = _share_at_least(similarities, self._ambiguous_from_similarity)
        if ambiguous_share >= self._min_chunk_share:
            return flag(DuplicateKind.OVERLAP, ambiguous_share, is_ambiguous=True)
        return None


def _share_at_least(similarities: tuple[float, ...], threshold: float) -> float:
    return sum(similarity >= threshold for similarity in similarities) / len(similarities)


def _strength(flag: DuplicateFlag) -> tuple[int, bool, float]:
    return _RANK_BY_KIND[flag.kind], flag.is_ambiguous, -flag.score
