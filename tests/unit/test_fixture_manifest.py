import csv
from pathlib import Path

FIXTURES_DIR = Path(__file__).parents[2] / "fixtures" / "docs"
MANIFEST_PATH = FIXTURES_DIR / "manifest.csv"
DOCUMENT_SUFFIXES = {".doc", ".docx", ".pdf"}


def _rows() -> list[dict[str, str]]:
    with MANIFEST_PATH.open(newline="", encoding="utf-8") as manifest:
        return list(csv.DictReader(manifest))


def test_manifest_lists_exactly_the_sample_files_when_compared_with_disk():
    on_disk = {
        path.relative_to(FIXTURES_DIR).as_posix()
        for path in FIXTURES_DIR.rglob("*")
        if path.suffix in DOCUMENT_SUFFIXES
    }

    assert {row["file"] for row in _rows()} == on_disk


def test_manifest_ids_are_unique_when_loaded():
    ids = [row["id"] for row in _rows()]

    assert len(ids) == len(set(ids))


def test_manifest_references_point_to_existing_ids_when_set():
    rows = _rows()
    ids = {row["id"] for row in rows}
    references = {
        row[column] for row in rows for column in ("previous_version_id", "duplicate_of")
    } - {""}

    assert references <= ids


def test_public_rows_have_source_and_license_when_origin_is_public():
    public_rows = [row for row in _rows() if row["origin"] == "public"]

    assert public_rows
    assert all(row["source_url"] and row["license"] for row in public_rows)
