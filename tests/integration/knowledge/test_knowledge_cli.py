import json
from collections.abc import Iterator
from pathlib import Path

import pytest
import structlog

from offline_rag.bootstrap import build_knowledge, build_organization
from offline_rag.knowledge.application.commands import RunIngestionStep
from offline_rag.knowledge.application.ports import IngestionLane
from offline_rag.knowledge.infrastructure.postgres_database import PostgresDatabase
from offline_rag.knowledge.infrastructure.postgres_knowledge_item_repository import (
    PostgresKnowledgeItemRepository,
)
from offline_rag.knowledge.interface.cli import EXIT_FAILED, EXIT_OK, main
from offline_rag.organization.interface.node_registry_file import read_node_registry
from offline_rag.settings import Settings

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parents[3]
FIXTURE_DOCS = ROOT / "fixtures" / "docs"


@pytest.fixture(autouse=True)
def _reset_logging() -> Iterator[None]:
    # `main` configures structlog for the whole process; later tests need the defaults.
    yield
    structlog.reset_defaults()


def _settings(tmp_path: Path, postgres_url: str) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        database_url=postgres_url,
        node_registry_path=ROOT / "fixtures" / "registry" / "nodes.csv",
        log_level="error",
        prompts_dir=ROOT / "prompts",
        model_manifest_path=ROOT / "models" / "manifest.yaml",
    )


def _register_case_study_nodes(settings: Settings) -> None:
    organization = build_organization(settings)
    try:
        for command in read_node_registry(settings.node_registry_path):
            organization.register_node_handler.register(command)
    finally:
        organization.close()


@pytest.fixture
def settings(tmp_path: Path, postgres_url: str) -> Settings:
    """Return settings for a schema whose Nodes are the case-study registry."""
    registered = _settings(tmp_path, postgres_url)
    _register_case_study_nodes(registered)
    return registered


@pytest.mark.parametrize(
    ("relative_path", "document_format"),
    [
        ("synthetic/inspection_sp12_riser_r3_2024.docx", "docx"),
        ("synthetic/project_report_sp12_riser_r3_integrity.pdf", "pdf"),
        ("cases/legacy_riser_ut_inspection_procedure_2017.doc", "doc"),
        ("cases/scanned_sp12_riser_r3_baseline_2021.pdf", "pdf"),
    ],
)
def test_fixture_file_is_registered_when_submitted(
    settings: Settings,
    capsys: pytest.CaptureFixture[str],
    relative_path: str,
    document_format: str,
):
    exit_code = main(
        [
            "submit",
            str(FIXTURE_DOCS / relative_path),
            "--node",
            "sp12_inspection_team",
            "--document-type",
            "inspection_report",
            "--tag",
            "riser",
        ],
        settings=settings,
    )

    result = json.loads(capsys.readouterr().out)
    assert exit_code == EXIT_OK
    with PostgresDatabase(settings.database_url, pool_size=1, connect_timeout_s=2) as database:
        version = PostgresKnowledgeItemRepository(database).get_by_id(result["item_id"]).versions[0]
    assert version.document_format.value == document_format
    assert (settings.data_dir / "source_files" / version.source_file_reference).is_file()
    assert version.metadata.tags == ("riser",)


@pytest.mark.parametrize(
    ("arguments", "code", "status"),
    [
        (["README.md", "--node", "sp12_inspection_team"], "KNOWLEDGE_UNSUPPORTED_FORMAT", 422),
        (
            ["missing.pdf", "--node", "sp12_inspection_team"],
            "KNOWLEDGE_SOURCE_FILE_NOT_READABLE",
            404,
        ),
        (
            ["fixtures/docs/synthetic/rfp_sp12_pump_failure_analysis.docx", "--node", "nope"],
            "KNOWLEDGE_OWNER_NODE_NOT_FOUND",
            404,
        ),
        (
            ["fixtures/docs/synthetic/rfp_sp12_pump_failure_analysis.docx", "--node", " nope"],
            "ORGANIZATION_INVALID_NODE_IDENTIFIER",
            422,
        ),
    ],
)
def test_problem_details_are_printed_when_submission_fails(
    settings: Settings,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
    code: str,
    status: int,
):
    monkeypatch.chdir(ROOT)

    exit_code = main(["submit", *arguments], settings=settings)

    captured = capsys.readouterr()
    problem = json.loads(captured.err.strip().splitlines()[-1])
    assert exit_code == EXIT_FAILED
    assert captured.out == ""
    assert problem["type"] == code
    assert problem["status"] == status
    assert "Traceback" not in problem["detail"]


INSPECTION_DOCX = FIXTURE_DOCS / "synthetic/inspection_sp12_riser_r3_2024.docx"


def test_submission_is_refused_until_organization_registers_the_node(
    tmp_path: Path, postgres_url: str, capsys: pytest.CaptureFixture[str]
):
    settings = _settings(tmp_path, postgres_url)
    arguments = ["submit", str(INSPECTION_DOCX), "--node", "sp12_inspection_team"]

    refused = _problem(arguments, settings, capsys)
    _register_case_study_nodes(settings)
    accepted = _run(arguments, settings, capsys)

    assert refused["type"] == "KNOWLEDGE_OWNER_NODE_NOT_FOUND"
    assert accepted["status"] == "queued"


INSPECTION_V2_DOCX = FIXTURE_DOCS / "cases/inspection_sp12_riser_r3_2026_v2.docx"


def _run(arguments: list[str], settings: Settings, capsys: pytest.CaptureFixture[str]) -> dict:  # type: ignore[type-arg]
    assert main(arguments, settings=settings) == EXIT_OK
    return json.loads(capsys.readouterr().out)  # type: ignore[no-any-return]


def _problem(arguments: list[str], settings: Settings, capsys: pytest.CaptureFixture[str]) -> dict:  # type: ignore[type-arg]
    assert main(arguments, settings=settings) == EXIT_FAILED
    return json.loads(capsys.readouterr().err.strip().splitlines()[-1])  # type: ignore[no-any-return]


def _submit_docx(settings: Settings, capsys: pytest.CaptureFixture[str]) -> dict:  # type: ignore[type-arg]
    return _run(
        ["submit", str(INSPECTION_DOCX), "--node", "sp12_inspection_team"], settings, capsys
    )


def _run_text_and_chunking_steps(settings: Settings, ingestion_id: str) -> None:
    """Do what a text worker and then a chunking worker do with the ingestion's messages."""
    knowledge = build_knowledge(settings)
    try:
        for lane in (IngestionLane.TEXT, IngestionLane.CHUNKING):
            knowledge.run_step_handler.run(RunIngestionStep(ingestion_id=ingestion_id, lane=lane))
    finally:
        knowledge.close()


def test_ingestion_is_queued_when_file_is_submitted(
    settings: Settings, capsys: pytest.CaptureFixture[str]
):
    submitted = _submit_docx(settings, capsys)

    status = _run(["status", submitted["ingestion_id"]], settings, capsys)

    assert submitted["status"] == "queued"
    assert submitted["version_tag"] == "v1"
    assert status["status"] == "queued"
    assert status["item_id"] == submitted["item_id"]


def test_content_is_not_found_when_no_worker_has_run_yet(
    settings: Settings, capsys: pytest.CaptureFixture[str]
):
    submitted = _submit_docx(settings, capsys)

    problem = _problem(["show-content", submitted["item_id"]], settings, capsys)

    assert problem["type"] == "KNOWLEDGE_EXTRACTED_CONTENT_NOT_FOUND"


def test_blocks_are_printed_when_the_worker_steps_have_run(
    settings: Settings, capsys: pytest.CaptureFixture[str]
):
    submitted = _submit_docx(settings, capsys)
    _run_text_and_chunking_steps(settings, submitted["ingestion_id"])

    shown = _run(["show-content", submitted["item_id"], "--limit", "2"], settings, capsys)
    status = _run(["status", submitted["ingestion_id"]], settings, capsys)

    assert status["status"] == "completed"
    assert shown["version_tag"] == "v1"
    assert shown["extraction"]["table_count"] == 2
    assert len(shown["blocks"]) == 2
    assert shown["blocks"][0]["heading_path"]


def test_chunks_are_printed_when_the_worker_steps_have_run(
    settings: Settings, capsys: pytest.CaptureFixture[str]
):
    submitted = _submit_docx(settings, capsys)
    _run_text_and_chunking_steps(settings, submitted["ingestion_id"])

    chunks = _run(["show-chunks", submitted["item_id"]], settings, capsys)
    status = _run(["status", submitted["ingestion_id"]], settings, capsys)

    assert status["chunk_count"] == chunks["chunk_count"] > 0
    assert status["duplicate_flags"] == []
    assert chunks["is_retrievable"] is True
    assert all(chunk["token_count"] <= settings.chunk_max_tokens for chunk in chunks["chunks"])


def test_new_version_is_published_and_old_chunks_are_superseded_when_a_file_changes(
    settings: Settings, capsys: pytest.CaptureFixture[str]
):
    submitted = _submit_docx(settings, capsys)
    _run_text_and_chunking_steps(settings, submitted["ingestion_id"])

    published = _run(
        [
            "publish-version",
            submitted["item_id"],
            str(INSPECTION_V2_DOCX),
            "--change-reason",
            "Adds 3 readings and a change note.",
        ],
        settings,
        capsys,
    )
    old = _run(["show-chunks", submitted["item_id"], "--version", "v1"], settings, capsys)

    assert (published["version_tag"], published["status"]) == ("v2", "queued")
    assert (old["is_retrievable"], old["active_version_tag"]) == (False, "v2")


def test_new_ingestion_is_queued_when_a_completed_version_is_reingested(
    settings: Settings, capsys: pytest.CaptureFixture[str]
):
    submitted = _submit_docx(settings, capsys)
    _run_text_and_chunking_steps(settings, submitted["ingestion_id"])

    reingested = _run(["reingest", submitted["item_id"], "--version", "v1"], settings, capsys)

    assert reingested["status"] == "queued"
    assert reingested["ingestion_id"] != submitted["ingestion_id"]


def test_reingest_is_refused_when_the_version_is_still_queued(
    settings: Settings, capsys: pytest.CaptureFixture[str]
):
    submitted = _submit_docx(settings, capsys)

    problem = _problem(["reingest", submitted["item_id"]], settings, capsys)

    assert problem["type"] == "KNOWLEDGE_INGESTION_ALREADY_RUNNING"
    assert problem["details"]["ingestion_id"] == submitted["ingestion_id"]


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        (["reingest", "no-such-item"], "KNOWLEDGE_ITEM_NOT_FOUND"),
        (["show-content", "no-such-item"], "KNOWLEDGE_ITEM_NOT_FOUND"),
        (["status", "no-such-ingestion"], "KNOWLEDGE_INGESTION_NOT_FOUND"),
    ],
)
def test_problem_details_are_printed_when_the_id_is_unknown(
    settings: Settings, capsys: pytest.CaptureFixture[str], arguments: list[str], code: str
):
    problem = _problem(arguments, settings, capsys)

    assert problem["type"] == code
    assert problem["status"] == 404
