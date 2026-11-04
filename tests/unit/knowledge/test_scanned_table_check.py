import pytest
from hypothesis import given
from hypothesis import strategies as st

from offline_rag.knowledge.domain.scanned_table_check import find_table_review_reason

HEADER = ("Location", "Measured (mm)")
ROWS = (("R-3 EL +8.5 m, 9 o'clock", "21.2"), ("R-3 EL +8.5 m, 6 o'clock", "21.0"))
LABELS = ("R-3 EL +8.5 m, 9 o'clock", "R-3 EL +8.5 m, 6 o'clock")
OCR_TABLE = [list(HEADER), *(list(row) for row in ROWS)]


def _reason(
    rows: tuple[tuple[str, ...], ...] = ROWS,
    labels: tuple[str, ...] = LABELS,
    ocr_tables: list[list[list[str]]] | None = None,
) -> str | None:
    return find_table_review_reason(
        header=HEADER,
        rows=rows,
        row_labels=labels,
        ocr_tables=[OCR_TABLE] if ocr_tables is None else ocr_tables,
    )


def test_table_is_trusted_when_both_models_read_the_same_cells():
    assert _reason() is None


def test_case_and_spacing_do_not_count_when_cells_are_compared():
    ocr = [
        ["location", "Measured(mm)"],
        ["R-3 EL+8.5 m,9 o'clock", "21.2"],
        ["r-3 el +8.5 m, 6 o'clock", "21.0"],
    ]

    assert _reason(ocr_tables=[ocr]) is None


def test_table_needs_review_when_a_digit_differs():
    ocr = [list(HEADER), ["R-3 EL +8.5 m, 9 o'clock", "21.2"], ["R-3 EL +8.5 m, 6 o'clock", "20.0"]]

    reason = _reason(ocr_tables=[ocr])

    assert reason == "Row 3, column 2 differs: LVM read '21.0', OCR read '20.0'."


def test_table_needs_review_when_there_are_more_rows_than_row_labels():
    reason = _reason(labels=LABELS[:1])

    assert reason == "The LVM read 2 rows but 1 row labels."


def test_table_needs_review_when_a_skipped_row_shifts_the_values():
    shifted_rows = (("R-3 EL +8.5 m, 6 o'clock", "21.2"), ("", "21.0"))

    reason = _reason(rows=shifted_rows)

    assert reason is not None
    assert "Data row 1 does not start with its row label" in reason


@pytest.mark.parametrize(
    "ocr_tables",
    [[], [[list(HEADER), list(ROWS[0])]], [[["Location"], ["a"], ["b"]]]],
    ids=["no-table", "fewer-rows", "fewer-columns"],
)
def test_table_needs_review_when_ocr_found_no_table_of_the_same_shape(
    ocr_tables: list[list[list[str]]],
):
    assert _reason(ocr_tables=ocr_tables) == "The OCR model found no 3 by 2 table to compare with."


def test_table_is_trusted_when_any_same_shaped_ocr_table_agrees():
    other_table = [["Field", "Value"], ["Document ID", "SCAN-01"], ["Revision", "1"]]

    assert _reason(ocr_tables=[other_table, OCR_TABLE]) is None


cells = st.text(alphabet="ABCabc0123456789.,+- ", min_size=1, max_size=8).filter(str.strip)


@given(rows=st.lists(st.tuples(cells, cells), min_size=1, max_size=6))
def test_table_is_trusted_when_ocr_returns_exactly_the_same_grid(rows: list[tuple[str, str]]):
    ocr = [list(HEADER), *(list(row) for row in rows)]

    assert (
        find_table_review_reason(
            header=HEADER,
            rows=rows,
            row_labels=[row[0] for row in rows],
            ocr_tables=[ocr],
        )
        is None
    )
