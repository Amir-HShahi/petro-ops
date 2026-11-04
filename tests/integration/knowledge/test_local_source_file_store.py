from pathlib import Path

import pytest

from offline_rag.knowledge.infrastructure.errors import SourceFileStorageError
from offline_rag.knowledge.infrastructure.local_source_file_store import LocalSourceFileStore

pytestmark = pytest.mark.integration


def test_file_is_written_unchanged_when_saved(tmp_path: Path):
    store = LocalSourceFileStore(tmp_path / "source_files")

    reference = store.save("Report R-3.PDF", b"%PDF-1.7 content")

    assert reference.endswith(".pdf")
    assert (tmp_path / "source_files" / reference).read_bytes() == b"%PDF-1.7 content"


def test_each_save_gets_its_own_file_when_names_repeat(tmp_path: Path):
    store = LocalSourceFileStore(tmp_path)

    first = store.save("report.pdf", b"first")
    second = store.save("report.pdf", b"second")

    assert first != second
    assert (tmp_path / first).read_bytes() == b"first"
    assert (tmp_path / second).read_bytes() == b"second"


@pytest.mark.parametrize("file_name", ["../../escape.pdf", "/etc/passwd", "a/b/c.docx"])
def test_file_stays_inside_the_folder_when_name_contains_a_path(tmp_path: Path, file_name: str):
    root = tmp_path / "source_files"
    store = LocalSourceFileStore(root)

    reference = store.save(file_name, b"content")

    assert (root / reference).resolve().parent == root.resolve()


def test_odd_suffix_is_dropped_when_it_is_not_short_and_simple(tmp_path: Path):
    store = LocalSourceFileStore(tmp_path)

    reference = store.save("report.pdf; rm -rf", b"content")

    assert "." not in reference


def test_folder_error_is_a_storage_error_when_root_is_a_file(tmp_path: Path):
    blocker = tmp_path / "source_files"
    blocker.write_text("not a folder")

    with pytest.raises(SourceFileStorageError) as caught:
        LocalSourceFileStore(blocker)

    assert caught.value.code == "KNOWLEDGE_SOURCE_FILE_STORAGE_FAILED"
