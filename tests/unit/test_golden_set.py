import csv
import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES_DIR = Path(__file__).parents[2] / "fixtures"
GOLDEN_DIR = FIXTURES_DIR / "golden"
MANIFEST_PATH = FIXTURES_DIR / "docs" / "manifest.csv"
NODES_PATH = FIXTURES_DIR / "registry" / "nodes.csv"
LAYERS_PATH = FIXTURES_DIR / "registry" / "layers.csv"

COMMON_FIELDS = {"id", "evidence", "review_status"}
REQUIRED_FIELDS = {
    "qa.jsonl": COMMON_FIELDS | {"question", "question_type", "node_id", "expected_answer"},
    "executor_matching.jsonl": COMMON_FIELDS
    | {"issue_title", "issue_description", "node_id", "expected_executor_ids"},
    "proposal_evaluation.jsonl": COMMON_FIELDS
    | {
        "rfp_doc_id",
        "proposal_doc_id",
        "expected_rank",
        "mandatory_requirements_met",
        "expected_critiques",
    },
    "issue_decomposition.jsonl": COMMON_FIELDS
    | {"issue_title", "issue_description", "node_id", "expected_sub_issues"},
    "transfer_summary.jsonl": COMMON_FIELDS
    | {
        "source_node_id",
        "target_layer_index",
        "detail_level",
        "must_include",
        "must_not_include",
    },
}
GOLDEN_FILES = sorted(REQUIRED_FIELDS)
QUESTION_TYPES = {
    "single_fact",
    "table_lookup",
    "multi_document",
    "version_sensitive",
    "scanned_pdf",
    "unanswerable",
    "layer_scope",
}
MIN_ROWS_PER_QUESTION_TYPE = 3
REVIEW_STATUSES = {"draft", "reviewed"}
EVIDENCE_FIELDS = {"doc_id", "page_or_section", "quote"}
MIN_QUOTE_WORDS, MAX_QUOTE_WORDS = 5, 25
MANDATORY_REQUIREMENTS = {"M1", "M2", "M3", "M4", "M5"}


def _golden_rows(name: str) -> list[dict[str, Any]]:
    lines = (GOLDEN_DIR / name).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


def _manifest() -> dict[str, dict[str, str]]:
    return {row["id"]: row for row in _csv_rows(MANIFEST_PATH)}


def _node_ids() -> set[str]:
    return {node["node_id"] for node in _csv_rows(NODES_PATH)}


def _subtree(root_node_id: str) -> set[str]:
    children: dict[str, list[str]] = {}
    for node in _csv_rows(NODES_PATH):
        children.setdefault(node["parent_node_id"], []).append(node["node_id"])
    subtree, pending = set(), [root_node_id]
    while pending:
        node_id = pending.pop()
        subtree.add(node_id)
        pending.extend(children.get(node_id, []))
    return subtree


def _evidence_nodes(row: dict[str, Any]) -> set[str]:
    manifest = _manifest()
    return {manifest[evidence["doc_id"]]["node"] for evidence in row["evidence"]}


def _qa_rows_of_type(question_type: str) -> list[dict[str, Any]]:
    return [row for row in _golden_rows("qa.jsonl") if row["question_type"] == question_type]


@pytest.mark.parametrize("name", GOLDEN_FILES)
def test_every_line_is_a_json_object_when_parsed(name: str):
    lines = (GOLDEN_DIR / name).read_text(encoding="utf-8").splitlines()

    assert lines
    for number, line in enumerate(lines, start=1):
        assert isinstance(json.loads(line), dict), f"{name}:{number}"


@pytest.mark.parametrize("name", GOLDEN_FILES)
def test_ids_are_unique_when_loaded(name: str):
    ids = [row["id"] for row in _golden_rows(name)]

    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("name", GOLDEN_FILES)
def test_rows_have_required_fields_when_loaded(name: str):
    for row in _golden_rows(name):
        assert REQUIRED_FIELDS[name] <= row.keys(), row.get("id")


@pytest.mark.parametrize("name", GOLDEN_FILES)
def test_rows_use_known_review_status_when_loaded(name: str):
    assert {row["review_status"] for row in _golden_rows(name)} <= REVIEW_STATUSES


@pytest.mark.parametrize("name", GOLDEN_FILES)
def test_evidence_points_to_manifest_documents_when_set(name: str):
    manifest = _manifest()

    for row in _golden_rows(name):
        for evidence in row["evidence"]:
            assert evidence.keys() == EVIDENCE_FIELDS, row["id"]
            assert evidence["doc_id"] in manifest, row["id"]
            assert evidence["page_or_section"], row["id"]
            quote_words = len(evidence["quote"].split())
            assert MIN_QUOTE_WORDS <= quote_words <= MAX_QUOTE_WORDS, row["id"]


@pytest.mark.parametrize("name", GOLDEN_FILES)
def test_evidence_cites_canonical_latest_documents_when_set(name: str):
    manifest = _manifest()
    superseded = {row["previous_version_id"] for row in manifest.values()} - {""}
    duplicates = {doc_id for doc_id, row in manifest.items() if row["duplicate_of"]}

    for row in _golden_rows(name):
        cited = {evidence["doc_id"] for evidence in row["evidence"]}
        assert not cited & (superseded | duplicates), row["id"]


@pytest.mark.parametrize("name", GOLDEN_FILES)
def test_node_ids_exist_in_registry_when_set(name: str):
    node_ids = _node_ids()
    node_fields = ("node_id", "asked_from_node_id", "source_node_id")

    for row in _golden_rows(name):
        for field in node_fields:
            if field in row:
                assert row[field] in node_ids, (row["id"], field)


def test_question_types_are_known_when_loaded():
    assert {row["question_type"] for row in _golden_rows("qa.jsonl")} <= QUESTION_TYPES


def test_qa_covers_every_question_type_when_loaded():
    for question_type in QUESTION_TYPES:
        rows = _qa_rows_of_type(question_type)
        assert len(rows) >= MIN_ROWS_PER_QUESTION_TYPE, question_type


def test_unanswerable_questions_have_no_evidence_when_loaded():
    for row in _qa_rows_of_type("unanswerable"):
        assert row["evidence"] == [], row["id"]
        assert "insufficient" in row["expected_answer"].lower(), row["id"]


def test_answerable_questions_have_evidence_when_loaded():
    for row in _golden_rows("qa.jsonl"):
        if row["question_type"] != "unanswerable":
            assert row["evidence"], row["id"]


def test_evidence_is_inside_node_scope_when_question_is_not_layer_scope():
    for row in _golden_rows("qa.jsonl"):
        if row["question_type"] != "layer_scope":
            assert _evidence_nodes(row) <= _subtree(row["node_id"]), row["id"]


def test_layer_scope_flag_matches_registry_when_question_is_layer_scope():
    for row in _qa_rows_of_type("layer_scope"):
        evidence_nodes = _evidence_nodes(row)
        assert evidence_nodes <= _subtree(row["node_id"]), row["id"]
        is_in_scope = evidence_nodes <= _subtree(row["asked_from_node_id"])
        assert row["is_in_scope"] is is_in_scope, row["id"]
        if not is_in_scope:
            assert "insufficient" in row["expected_answer"].lower(), row["id"]


def test_layer_scope_covers_both_outcomes_when_loaded():
    assert {row["is_in_scope"] for row in _qa_rows_of_type("layer_scope")} == {True, False}


def test_expected_executors_are_canonical_personnel_profiles_when_set():
    manifest = _manifest()

    for row in _golden_rows("executor_matching.jsonl"):
        assert row["expected_executor_ids"], row["id"]
        for executor_id in row["expected_executor_ids"]:
            assert manifest[executor_id]["document_type"] == "personnel_profile", row["id"]
            assert not manifest[executor_id]["duplicate_of"], row["id"]


def test_executor_evidence_cites_expected_profiles_when_set():
    for row in _golden_rows("executor_matching.jsonl"):
        cited = {evidence["doc_id"] for evidence in row["evidence"]}
        assert set(row["expected_executor_ids"]) <= cited, row["id"]


def test_proposal_rows_reference_rfp_and_proposal_documents_when_loaded():
    manifest = _manifest()
    rows = _golden_rows("proposal_evaluation.jsonl")
    proposals = {doc_id for doc_id, row in manifest.items() if row["document_type"] == "proposal"}

    assert {row["proposal_doc_id"] for row in rows} == proposals
    for row in rows:
        assert manifest[row["rfp_doc_id"]]["document_type"] == "rfp", row["id"]


def test_proposal_ranks_are_a_permutation_when_loaded():
    ranks = sorted(row["expected_rank"] for row in _golden_rows("proposal_evaluation.jsonl"))

    assert ranks == list(range(1, len(ranks) + 1))


def test_mandatory_requirements_are_booleans_when_loaded():
    for row in _golden_rows("proposal_evaluation.jsonl"):
        met = row["mandatory_requirements_met"]
        assert met.keys() == MANDATORY_REQUIREMENTS, row["id"]
        assert all(isinstance(value, bool) for value in met.values()), row["id"]


def test_best_ranked_proposal_meets_every_mandatory_requirement_when_loaded():
    best = min(_golden_rows("proposal_evaluation.jsonl"), key=lambda row: row["expected_rank"])

    assert all(best["mandatory_requirements_met"].values())


def test_critiques_name_a_criterion_when_set():
    for row in _golden_rows("proposal_evaluation.jsonl"):
        assert row["expected_critiques"], row["id"]
        for critique in row["expected_critiques"]:
            assert critique.keys() == {"criterion", "summary"}, row["id"]
            assert critique["criterion"], row["id"]
            assert critique["summary"], row["id"]


def test_issue_decomposition_has_sub_issues_when_loaded():
    for row in _golden_rows("issue_decomposition.jsonl"):
        assert len(row["expected_sub_issues"]) >= 2, row["id"]
        assert row["evidence"], row["id"]


def test_transfer_detail_level_matches_target_layer_when_loaded():
    detail_levels = {
        int(layer["layer_index"]): layer["received_detail_level"]
        for layer in _csv_rows(LAYERS_PATH)
    }

    for row in _golden_rows("transfer_summary.jsonl"):
        assert row["detail_level"] == detail_levels[row["target_layer_index"]], row["id"]


def test_transfer_targets_a_higher_layer_when_loaded():
    layer_by_node = {node["node_id"]: int(node["layer_index"]) for node in _csv_rows(NODES_PATH)}

    for row in _golden_rows("transfer_summary.jsonl"):
        assert row["target_layer_index"] < layer_by_node[row["source_node_id"]], row["id"]
        assert row["must_include"], row["id"]
        assert row["evidence"], row["id"]


def test_transfer_evidence_belongs_to_source_node_scope_when_set():
    for row in _golden_rows("transfer_summary.jsonl"):
        assert _evidence_nodes(row) <= _subtree(row["source_node_id"]), row["id"]
