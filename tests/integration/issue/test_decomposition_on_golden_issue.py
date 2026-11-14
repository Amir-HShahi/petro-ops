"""The real LLM splits a golden Issue, reading the document its evidence comes from.

Golden case `id-001` (`fixtures/golden/issue_decomposition.jsonl`) cites only
`ins-02-v2`, the 2026 R-3 inspection report, so the model gets that one item.
"""

import json
import urllib.request
from pathlib import Path

import pytest

from offline_rag.bootstrap import build_issue, build_knowledge
from offline_rag.issue.application.commands import DecomposeIssue, RaiseIssue
from offline_rag.knowledge.application.commands import RunIngestionStep, SubmitKnowledgeItem
from offline_rag.knowledge.application.ports import IngestionLane
from offline_rag.knowledge.domain.knowledge_scope import ConfidentialityLevel, KnowledgeScope
from offline_rag.settings import Settings
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

pytestmark = [pytest.mark.integration, pytest.mark.slow]

ROOT = Path(__file__).parents[3]
INSPECTION_V2 = ROOT / "fixtures" / "docs" / "cases" / "inspection_sp12_riser_r3_2026_v2.docx"
GOLDEN = ROOT / "fixtures" / "golden" / "issue_decomposition.jsonl"
OLLAMA_URL = "http://127.0.0.1:11434"


def _golden_case(case_id: str) -> dict:  # type: ignore[type-arg]
    for line in GOLDEN.read_text(encoding="utf-8").splitlines():
        case = json.loads(line)
        if case["id"] == case_id:
            return case  # type: ignore[no-any-return]
    raise LookupError(case_id)


@pytest.fixture
def real_model_settings(settings: Settings) -> Settings:
    try:
        urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=2).close()
    except OSError:
        pytest.skip("Ollama is not running")
    return settings.model_copy(update={"ollama_url": OLLAMA_URL})


def test_golden_issue_is_split_into_cited_candidates_when_decomposed(
    real_model_settings: Settings,
):
    case = _golden_case("id-001")
    knowledge = build_knowledge(real_model_settings)
    try:
        receipt = knowledge.submit_handler.submit(
            SubmitKnowledgeItem(
                owner_node_id=NodeIdentifier("sp12_inspection_team"),
                source_file_name=INSPECTION_V2.name,
                content=INSPECTION_V2.read_bytes(),
                scope=KnowledgeScope(confidentiality=ConfidentialityLevel.INTERNAL),
            )
        )
        for lane in (IngestionLane.TEXT, IngestionLane.CHUNKING):
            knowledge.run_step_handler.run(
                RunIngestionStep(ingestion_id=receipt.ingestion_id, lane=lane)
            )
    finally:
        knowledge.close()

    issue = build_issue(real_model_settings)
    try:
        raised = issue.raise_issue_handler.raise_issue(
            RaiseIssue(
                owner_node_id=NodeIdentifier(case["node_id"]),
                title=case["issue_title"],
                description=case["issue_description"],
                metadata=MetadataRecord(),
            )
        )
        result = issue.decompose_issue_handler.decompose(
            DecomposeIssue(issue_id=raised.issue_id, knowledge_item_ids=(receipt.item_id,))
        )
    finally:
        issue.close()

    for candidate in result.candidates:
        print(candidate.number, candidate.title, f"({len(candidate.citations)} citations)")
    print("dropped citations:", result.dropped_citation_count)
    print("expected:", case["expected_sub_issues"])

    cited = [candidate for candidate in result.candidates if candidate.citations]
    assert len(result.candidates) >= 3
    assert len(cited) >= len(result.candidates) / 2
    assert all(
        citation.doc_id == receipt.item_id
        for candidate in result.candidates
        for citation in candidate.citations
    )
