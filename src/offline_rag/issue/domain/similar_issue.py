"""The SimilarIssueDetector domain service and the flags it raises (spec §12.1, ADR 0012).

The detector only names similar Issues. A new Issue is always created; its flags
tell the Node that it may repeat or overlap Issues it already has.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from offline_rag.issue.domain.issue_text import (
    issue_words,
    names_other_equipment,
    word_similarity,
)
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

if TYPE_CHECKING:
    from offline_rag.issue.domain.issue import Issue


class SimilarIssueKind(StrEnum):
    """How a new Issue looks like an existing Issue of the same Node (spec §12.1, step 4)."""

    DUPLICATE = "duplicate"
    """Probably the same problem, described again."""
    OVERLAP = "overlap"
    """A related problem: they share part of their subject."""


@dataclass(frozen=True, kw_only=True, slots=True)
class SimilarIssueFlag:
    """An existing Issue of the same Node that a new Issue looks like.

    A flag is a finding, not a decision: both Issues are kept.

    Attributes:
        similar_issue_id: The existing Issue.
        kind: Whether it is probably the same problem or a related one.
        score: The word similarity of the two texts, from 0 to 1.
    """

    similar_issue_id: str
    kind: SimilarIssueKind
    score: float


class SimilarIssueDetector:
    """Finds which existing Issues of the same Node a new Issue repeats or overlaps.

    Rules (docs/domain-model.md, `SimilarIssueDetector`; ADR 0012):
    1. Only Issues of the same Node are compared (spec §12.1).
    2. The score is the word similarity of title and description.
    3. From `duplicate_from` it is a duplicate, unless each text names equipment the
       other does not; then it is an overlap at most.
    4. From `overlap_from` it is an overlap.

    The flags come strongest first. The service is pure.
    """

    def __init__(self, *, duplicate_from: float, overlap_from: float) -> None:
        """Create the detector.

        Args:
            duplicate_from: Similarity, from 0 to 1, from which an Issue is a likely
                duplicate.
            overlap_from: Lower similarity, from which it overlaps. Below
                `duplicate_from`.
        """
        self._duplicate_from = duplicate_from
        self._overlap_from = overlap_from

    def detect(
        self,
        *,
        owner_node_id: NodeIdentifier,
        title: str,
        description: str,
        existing: Sequence["Issue"],
    ) -> tuple[SimilarIssueFlag, ...]:
        """Return a flag for each existing Issue the new one repeats or overlaps.

        Args:
            owner_node_id: The Node of the new Issue.
            title: The title of the new Issue.
            description: The description of the new Issue.
            existing: Issues to compare with. Those of other Nodes are skipped.
        """
        words = issue_words(title, description)
        flags: list[SimilarIssueFlag] = []
        for other in existing:
            if other.owner_node_id != owner_node_id:
                continue
            other_words = issue_words(other.title, other.description)
            score = round(word_similarity(words, other_words), 4)
            kind = self._kind(score, is_other_equipment=names_other_equipment(words, other_words))
            if kind is not None:
                flags.append(
                    SimilarIssueFlag(similar_issue_id=other.issue_id, kind=kind, score=score)
                )
        return tuple(
            sorted(
                flags,
                key=lambda flag: (
                    flag.kind != SimilarIssueKind.DUPLICATE,
                    -flag.score,
                    flag.similar_issue_id,
                ),
            )
        )

    def _kind(self, score: float, *, is_other_equipment: bool) -> SimilarIssueKind | None:
        if score >= self._duplicate_from and not is_other_equipment:
            return SimilarIssueKind.DUPLICATE
        if score >= self._overlap_from:
            return SimilarIssueKind.OVERLAP
        return None
