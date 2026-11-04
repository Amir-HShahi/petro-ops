import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
import structlog

from offline_rag.knowledge.interface.cli import EXIT_FAILED, EXIT_OK, main
from offline_rag.settings import Settings

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parents[3]
FIXTURE_DOCS = ROOT / "fixtures" / "docs"


@pytest.fixture(autouse=True)
def _reset_logging() -> Iterator[None]:
    # `main` configures structlog for the whole process; later tests need the defaults.
    yield
    structlog.reset_defaults()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        node_registry_path=ROOT / "fixtures" / "registry" / "nodes.csv",
        log_level="error",
    )


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
    with sqlite3.connect(settings.data_dir / "knowledge.sqlite3") as connection:
        row = connection.execute(
            "SELECT document_format, source_file_reference, metadata_json "
            "FROM knowledge_versions WHERE item_id = ?",
            (result["item_id"],),
        ).fetchone()
    assert row[0] == document_format
    assert (settings.data_dir / "source_files" / row[1]).is_file()
    assert json.loads(row[2])["tags"] == ["riser"]


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


def _run(arguments: list[str], settings: Settings, capsys: pytest.CaptureFixture[str]) -> dict:  # type: ignore[type-arg]
    assert main(arguments, settings=settings) == EXIT_OK
    return json.loads(capsys.readouterr().out)  # type: ignore[no-any-return]


def test_content_is_extracted_when_file_is_submitted(
    settings: Settings, capsys: pytest.CaptureFixture[str]
):
    result = _run(
        [
            "submit",
            str(FIXTURE_DOCS / "synthetic/inspection_sp12_riser_r3_2024.docx"),
            "--node",
            "sp12_inspection_team",
        ],
        settings,
        capsys,
    )

    assert result["version_tag"] == "v1"
    assert result["extraction"]["document_format"] == "docx"
    assert result["extraction"]["block_count"] > 0
    assert result["extraction"]["table_count"] == 2


def test_scanned_page_is_reported_for_the_lvm_when_scanned_pdf_is_submitted(
    settings: Settings, capsys: pytest.CaptureFixture[str]
):
    result = _run(
        [
            "submit",
            str(FIXTURE_DOCS / "cases/scanned_sp12_riser_r3_baseline_2021.pdf"),
            "--node",
            "sp12_inspection_team",
        ],
        settings,
        capsys,
    )

    assert result["extraction"]["pages_without_text"] == [1]


def test_registration_stands_without_extraction_when_doc_converter_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    settings = Settings(
        data_dir=tmp_path / "data",
        node_registry_path=ROOT / "fixtures" / "registry" / "nodes.csv",
        log_level="error",
        libreoffice_path="soffice-that-does-not-exist",
    )

    result = _run(
        [
            "submit",
            str(FIXTURE_DOCS / "cases/legacy_riser_ut_inspection_procedure_2017.doc"),
            "--node",
            "sp12_inspection_team",
        ],
        settings,
        capsys,
    )

    assert result["extraction"] is None
    assert main(["show-content", result["item_id"]], settings=settings) == EXIT_FAILED
    problem = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert problem["type"] == "KNOWLEDGE_EXTRACTED_CONTENT_NOT_FOUND"


def test_blocks_are_printed_when_content_is_shown(
    settings: Settings, capsys: pytest.CaptureFixture[str]
):
    submitted = _run(
        [
            "submit",
            str(FIXTURE_DOCS / "synthetic/project_report_sp12_riser_r3_integrity.pdf"),
            "--node",
            "sp12_inspection_team",
        ],
        settings,
        capsys,
    )

    shown = _run(["show-content", submitted["item_id"], "--limit", "2"], settings, capsys)

    assert len(shown["blocks"]) == 2
    assert shown["blocks"][0]["page_number"] == 1
    assert shown["blocks"][0]["source"] == "text_layer"


def test_extraction_runs_again_when_extract_is_called(
    settings: Settings, capsys: pytest.CaptureFixture[str]
):
    submitted = _run(
        [
            "submit",
            str(FIXTURE_DOCS / "synthetic/project_report_sp12_riser_r3_integrity.pdf"),
            "--node",
            "sp12_inspection_team",
        ],
        settings,
        capsys,
    )

    extracted = _run(["extract", submitted["item_id"], "--version-tag", "v1"], settings, capsys)

    assert extracted["extraction"] == submitted["extraction"]


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        (["extract", "no-such-item"], "KNOWLEDGE_ITEM_NOT_FOUND"),
        (["show-content", "no-such-item"], "KNOWLEDGE_EXTRACTED_CONTENT_NOT_FOUND"),
    ],
)
def test_problem_details_are_printed_when_item_is_unknown(
    settings: Settings, capsys: pytest.CaptureFixture[str], arguments: list[str], code: str
):
    assert main(arguments, settings=settings) == EXIT_FAILED

    problem = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert problem["type"] == code
    assert problem["status"] == 404
