"""The similar-Issue rules on the golden Issues and hand-written variants (ADR 0012).

The thresholds are the defaults in `Settings`; the scores in the comments are the
ones measured when they were chosen.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from offline_rag.issue.domain.issue import Issue
from offline_rag.issue.domain.similar_issue import (
    SimilarIssueDetector,
    SimilarIssueFlag,
    SimilarIssueKind,
)
from offline_rag.settings import Settings
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

GOLDEN = Path(__file__).parents[3] / "fixtures" / "golden" / "issue_decomposition.jsonl"
PLATFORM = NodeIdentifier("platform_sp12")


def _golden_texts() -> dict[str, tuple[str, str]]:
    texts = {}
    for line in GOLDEN.read_text(encoding="utf-8").splitlines():
        case = json.loads(line)
        texts[case["id"]] = (case["issue_title"], case["issue_description"])
    return texts


GOLDEN_TEXTS = _golden_texts()
VARIANTS = {
    "riser-r3-reworded": (
        "Splash zone corrosion on riser R-3",
        "Riser R-3 on SP-12 is losing wall in the splash zone because the coating failed "
        "and cathodic protection does not reach it.",
    ),
    "riser-r3-short": (
        "Riser R-3 wall loss in splash zone",
        "Wall loss found on gas export riser R-3 splash zone.",
    ),
    "riser-r2-coating": (
        "Coating failure on riser R-2",
        "The coating on gas riser R-2 has failed in the splash zone and wall loss has not "
        "been measured yet.",
    ),
    "pump-p4101a-again": (
        "Seawater lift pump P-4101A keeps tripping",
        "Pump P-4101A tripped again, the third trip since the motor was replaced in July.",
    ),
    "compressor-k101": (
        "Gas compressor K-101 vibration",
        "Vibration on compressor K-101 bearing rose above alarm level during the last shift.",
    ),
}
TEXTS = GOLDEN_TEXTS | VARIANTS


def _issue(case_id: str, owner: NodeIdentifier = PLATFORM) -> Issue:
    title, description = TEXTS[case_id]
    return Issue.raise_issue(
        issue_id=case_id,
        owner_node_id=owner,
        title=title,
        description=description,
        metadata=MetadataRecord(),
        raised_at=datetime(2026, 11, 14, 9, 0, tzinfo=UTC),
    )


@pytest.fixture
def detector() -> SimilarIssueDetector:
    settings = Settings()
    return SimilarIssueDetector(
        duplicate_from=settings.similar_issue_duplicate_from,
        overlap_from=settings.similar_issue_overlap_from,
    )


def _kind(detector: SimilarIssueDetector, new: str, existing: str) -> SimilarIssueKind | None:
    title, description = TEXTS[new]
    flags = detector.detect(
        owner_node_id=PLATFORM, title=title, description=description, existing=[_issue(existing)]
    )
    return flags[0].kind if flags else None


@pytest.mark.parametrize(
    ("new", "existing", "kind"),
    [
        # 0.65: the same problem in other words.
        ("riser-r3-reworded", "id-001", SimilarIssueKind.DUPLICATE),
        # 0.40: a short note about the same riser.
        ("riser-r3-short", "id-001", SimilarIssueKind.DUPLICATE),
        # 0.41: the pump trips again.
        ("pump-p4101a-again", "id-002", SimilarIssueKind.DUPLICATE),
        # 0.57, but R-2 and R-3 are different risers.
        ("riser-r2-coating", "riser-r3-short", SimilarIssueKind.OVERLAP),
        # 0.37: coating failure on another riser.
        ("riser-r2-coating", "id-001", SimilarIssueKind.OVERLAP),
        # 0.31: the standby pump that took over from the tripping one.
        ("id-004", "id-002", SimilarIssueKind.OVERLAP),
        # 0.28: coating breakdown is part of the corrosion problem.
        ("id-005", "id-001", SimilarIssueKind.OVERLAP),
        # 0.13 and below: different subjects.
        ("id-003", "id-001", None),
        ("compressor-k101", "id-002", None),
        ("compressor-k101", "riser-r3-short", None),
    ],
)
def test_issue_is_flagged_by_its_word_similarity_when_compared(
    detector: SimilarIssueDetector, new: str, existing: str, kind: SimilarIssueKind | None
):
    assert _kind(detector, new, existing) == kind


def test_issues_of_other_nodes_are_skipped_when_compared(detector: SimilarIssueDetector):
    title, description = TEXTS["riser-r3-reworded"]

    flags = detector.detect(
        owner_node_id=PLATFORM,
        title=title,
        description=description,
        existing=[_issue("id-001", owner=NodeIdentifier("sp12_inspection_team"))],
    )

    assert flags == ()


def test_flags_come_duplicates_first_then_by_score_when_several_match(
    detector: SimilarIssueDetector,
):
    title, description = TEXTS["riser-r3-reworded"]

    flags = detector.detect(
        owner_node_id=PLATFORM,
        title=title,
        description=description,
        existing=[_issue(case) for case in ("riser-r2-coating", "riser-r3-short", "id-001")],
    )

    assert [(flag.similar_issue_id, flag.kind) for flag in flags] == [
        ("id-001", SimilarIssueKind.DUPLICATE),
        ("riser-r3-short", SimilarIssueKind.DUPLICATE),
        ("riser-r2-coating", SimilarIssueKind.OVERLAP),
    ]
    assert flags[0] == SimilarIssueFlag(
        similar_issue_id="id-001", kind=SimilarIssueKind.DUPLICATE, score=flags[0].score
    )
    assert 0 < flags[-1].score < flags[0].score <= 1
