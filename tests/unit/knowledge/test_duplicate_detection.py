import pytest
from hypothesis import given
from hypothesis import strategies as st

from offline_rag.knowledge.domain.duplicate_detection import (
    DuplicateComparison,
    DuplicateDetector,
    DuplicateFlag,
    DuplicateKind,
    VersionFingerprint,
)
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

V1 = VersionTag("v1")
TEAM = NodeIdentifier("sp12_inspection_team")
PLATFORM = NodeIdentifier("platform_sp12")
REPORT = MetadataRecord(document_type="inspection_report")
CANDIDATE = VersionFingerprint(
    item_id="ki-new",
    version_tag=V1,
    owner_node_id=TEAM,
    content_hash="file-new",
    normalized_text_hash="text-new",
    metadata=REPORT,
)


@pytest.fixture
def detector() -> DuplicateDetector:
    return DuplicateDetector(
        overlap_chunk_similarity=0.4, ambiguous_from_similarity=0.25, min_chunk_share=0.2
    )


def _existing(
    item_id: str = "ki-old",
    *,
    content_hash: str = "file-old",
    normalized_text_hash: str | None = "text-old",
    metadata: MetadataRecord = REPORT,
    owner_node_id: NodeIdentifier = TEAM,
) -> VersionFingerprint:
    return VersionFingerprint(
        item_id=item_id,
        version_tag=V1,
        owner_node_id=owner_node_id,
        content_hash=content_hash,
        normalized_text_hash=normalized_text_hash,
        metadata=metadata,
    )


def _flag(kind: DuplicateKind, score: float = 1.0, *, is_ambiguous: bool = False) -> DuplicateFlag:
    return DuplicateFlag(
        item_id="ki-new",
        version_tag=V1,
        kind=kind,
        existing_item_id="ki-old",
        existing_version_tag=V1,
        score=score,
        is_ambiguous=is_ambiguous,
    )


def test_exact_duplicate_is_flagged_when_file_hashes_are_equal(detector: DuplicateDetector):
    existing = _existing(content_hash="file-new", normalized_text_hash="text-new")

    flags = detector.detect(CANDIDATE, [DuplicateComparison(existing=existing)])

    assert flags == (_flag(DuplicateKind.EXACT),)


def test_near_duplicate_is_flagged_when_text_hashes_are_equal(detector: DuplicateDetector):
    flags = detector.detect(
        CANDIDATE, [DuplicateComparison(existing=_existing(normalized_text_hash="text-new"))]
    )

    assert flags == (_flag(DuplicateKind.NEAR),)


def test_metadata_variant_is_flagged_when_text_is_equal_but_metadata_differs(
    detector: DuplicateDetector,
):
    existing = _existing(
        normalized_text_hash="text-new", metadata=MetadataRecord(document_type="shift_report")
    )

    flags = detector.detect(CANDIDATE, [DuplicateComparison(existing=existing)])

    assert flags == (_flag(DuplicateKind.METADATA_VARIANT),)


def test_overlap_is_flagged_with_the_chunk_share_when_enough_chunks_repeat_the_item(
    detector: DuplicateDetector,
):
    comparison = DuplicateComparison(existing=_existing(), chunk_similarities=(0.0, 0.0, 0.54, 0.0))

    flags = detector.detect(CANDIDATE, [comparison])

    assert flags == (_flag(DuplicateKind.OVERLAP, 0.25),)


def test_overlap_is_marked_ambiguous_when_chunks_only_reach_the_gray_band(
    detector: DuplicateDetector,
):
    comparison = DuplicateComparison(existing=_existing(), chunk_similarities=(0.3, 0.0, 0.0))

    flags = detector.detect(CANDIDATE, [comparison])

    assert flags == (_flag(DuplicateKind.OVERLAP, 1 / 3, is_ambiguous=True),)


@pytest.mark.parametrize(
    "similarities",
    [(0.19, 0.0, 0.0), (0.9, 0.0, 0.0, 0.0, 0.0, 0.0), ()],
)
def test_no_flag_is_raised_when_too_few_chunks_repeat_the_item(
    detector: DuplicateDetector, similarities: tuple[float, ...]
):
    comparison = DuplicateComparison(existing=_existing(), chunk_similarities=similarities)

    assert detector.detect(CANDIDATE, [comparison]) == ()


def test_items_of_another_node_are_ignored_when_the_file_is_the_same(
    detector: DuplicateDetector,
):
    existing = _existing(content_hash="file-new", owner_node_id=PLATFORM)

    assert detector.detect(CANDIDATE, [DuplicateComparison(existing=existing)]) == ()


def test_own_item_is_ignored_when_an_older_version_is_compared(detector: DuplicateDetector):
    older = _existing(item_id="ki-new", normalized_text_hash="text-new")

    assert detector.detect(CANDIDATE, [DuplicateComparison(existing=older)]) == ()


def test_only_the_strongest_flag_is_kept_when_one_item_is_compared_twice(
    detector: DuplicateDetector,
):
    overlapping = DuplicateComparison(existing=_existing(), chunk_similarities=(0.9,))
    same_file = DuplicateComparison(existing=_existing(content_hash="file-new"))

    flags = detector.detect(CANDIDATE, [overlapping, same_file])

    assert [flag.kind for flag in flags] == [DuplicateKind.EXACT]


def test_flags_come_ordered_by_item_id_when_several_items_are_repeated(
    detector: DuplicateDetector,
):
    comparisons = [
        DuplicateComparison(existing=_existing("ki-b", content_hash="file-new")),
        DuplicateComparison(existing=_existing("ki-a", content_hash="file-new")),
    ]

    flags = detector.detect(CANDIDATE, comparisons)

    assert [flag.existing_item_id for flag in flags] == ["ki-a", "ki-b"]


def test_text_hash_is_not_compared_when_the_candidate_has_none_yet(detector: DuplicateDetector):
    candidate = VersionFingerprint(
        item_id="ki-new",
        version_tag=V1,
        owner_node_id=TEAM,
        content_hash="file-new",
        normalized_text_hash=None,
        metadata=REPORT,
    )

    flags = detector.detect(
        candidate, [DuplicateComparison(existing=_existing(normalized_text_hash=None))]
    )

    assert flags == ()


@given(st.lists(st.floats(min_value=0, max_value=1), max_size=20))
def test_every_flag_has_a_score_from_0_to_1_when_similarities_vary(similarities: list[float]):
    detector = DuplicateDetector(
        overlap_chunk_similarity=0.4, ambiguous_from_similarity=0.25, min_chunk_share=0.2
    )
    comparison = DuplicateComparison(existing=_existing(), chunk_similarities=tuple(similarities))

    flags = detector.detect(CANDIDATE, [comparison])

    assert all(0 < flag.score <= 1 for flag in flags)
    assert all(flag.kind == DuplicateKind.OVERLAP for flag in flags)
