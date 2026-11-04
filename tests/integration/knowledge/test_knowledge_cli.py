import json
import sqlite3
from pathlib import Path

import pytest

from offline_rag.knowledge.interface.cli import EXIT_FAILED, EXIT_OK, main
from offline_rag.settings import Settings

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parents[3]
FIXTURE_DOCS = ROOT / "fixtures" / "docs"


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
