"""What submitting, publishing and chunking share about duplicates (spec §7.7, ADR 0010)."""

from collections.abc import Sequence
from datetime import datetime

from offline_rag.knowledge.application.ports import VersionFingerprintRepository
from offline_rag.knowledge.domain.duplicate_detection import (
    DuplicateComparison,
    DuplicateDetector,
    DuplicateFlag,
    VersionFingerprint,
)
from offline_rag.knowledge.domain.events import DuplicateDetected
from offline_rag.knowledge.domain.knowledge_item import KnowledgeItem
from offline_rag.knowledge.domain.knowledge_version import KnowledgeVersion


def fingerprint_of(
    item: KnowledgeItem, version: KnowledgeVersion, normalized_text_hash: str | None = None
) -> VersionFingerprint:
    """Return what the detector compares of a version of an item."""
    return VersionFingerprint(
        item_id=item.item_id,
        version_tag=version.version_tag,
        owner_node_id=item.owner_node_id,
        content_hash=version.content_hash,
        normalized_text_hash=normalized_text_hash,
        metadata=version.metadata,
    )


def find_exact_duplicates(
    candidate: VersionFingerprint,
    *,
    fingerprints: VersionFingerprintRepository,
    detector: DuplicateDetector,
) -> tuple[DuplicateFlag, ...]:
    """Return the flags for other items of the same Node that have the very same file.

    This is the only check that can run before the file is parsed; the others
    wait for the chunking step.
    """
    same_file = fingerprints.find_by_content_hash(candidate.owner_node_id, candidate.content_hash)
    return detector.detect(candidate, [DuplicateComparison(existing=found) for found in same_file])


def duplicate_detected_events(
    flags: Sequence[DuplicateFlag], *, occurred_at: datetime
) -> list[DuplicateDetected]:
    """Return one `DuplicateDetected` event per flag."""
    return [
        DuplicateDetected(
            occurred_at=occurred_at,
            item_id=flag.item_id,
            version_tag=flag.version_tag,
            kind=flag.kind,
            existing_item_id=flag.existing_item_id,
            existing_version_tag=flag.existing_version_tag,
            score=flag.score,
            is_ambiguous=flag.is_ambiguous,
        )
        for flag in flags
    ]
