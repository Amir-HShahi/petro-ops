"""The check that decides whether a table read from a scan can be trusted (ADR 0002).

Gemma can skip a row on a hard scan, so every later value moves up one row with
no error shown. `glm-ocr` keeps row order better, so every scanned table is read
by both, and a table they disagree on goes to a person.
"""

import re
from collections.abc import Sequence

from offline_rag.knowledge.domain.extracted_content import normalize_extracted_text

TableGrid = Sequence[Sequence[str]]

_SPACE_AROUND_PUNCTUATION = re.compile(r"\s*([,.:;()/+-])\s*")


def find_table_review_reason(
    *,
    header: Sequence[str],
    rows: TableGrid,
    row_labels: Sequence[str],
    ocr_tables: Sequence[TableGrid],
) -> str | None:
    """Return why a scanned table needs human review, or None when it can be trusted.

    Args:
        header: The table's header row, as the LVM read it.
        rows: The data rows, as the LVM read them.
        row_labels: The first cell of each data row, which the LVM reads a second
            time on its own. A skipped row makes them stop lining up with `rows`.
        ocr_tables: Every table the OCR model found on the same page.

    The rules, checked in order:
    1. There is one row label per data row.
    2. Each row starts with its row label.
    3. The OCR model found a table with the same number of rows and columns.
    4. Every cell matches that OCR table. Case, spaces and spaces around
       punctuation do not count, but digits do: 13.6 and 13.4 differ.
    """
    if len(row_labels) != len(rows):
        return f"The LVM read {len(rows)} rows but {len(row_labels)} row labels."
    for index, (row, label) in enumerate(zip(rows, row_labels, strict=True), start=1):
        if not row or _cell_key(row[0]) != _cell_key(label):
            return f"Data row {index} does not start with its row label '{label}'."

    lvm_grid = [list(header), *(list(row) for row in rows)]
    same_shape = [table for table in ocr_tables if _shape(table) == _shape(lvm_grid)]
    if not same_shape:
        return (
            f"The OCR model found no {len(lvm_grid)} by {_column_count(lvm_grid)} table "
            "to compare with."
        )

    differences = [_first_difference(lvm_grid, table) for table in same_shape]
    if any(difference is None for difference in differences):
        return None
    return differences[0]


def _cell_key(cell: str) -> str:
    text = normalize_extracted_text(cell).replace("\n", " ").casefold()
    return _SPACE_AROUND_PUNCTUATION.sub(r"\1", text)


def _shape(table: TableGrid) -> tuple[int, int]:
    return len(table), _column_count(table)


def _column_count(table: TableGrid) -> int:
    return max((len(row) for row in table), default=0)


def _first_difference(lvm_grid: TableGrid, ocr_grid: TableGrid) -> str | None:
    for row_index, (lvm_row, ocr_row) in enumerate(zip(lvm_grid, ocr_grid, strict=True)):
        for column_index in range(_column_count(lvm_grid)):
            lvm_cell = lvm_row[column_index] if column_index < len(lvm_row) else ""
            ocr_cell = ocr_row[column_index] if column_index < len(ocr_row) else ""
            if _cell_key(lvm_cell) != _cell_key(ocr_cell):
                return (
                    f"Row {row_index + 1}, column {column_index + 1} differs: "
                    f"LVM read '{lvm_cell}', OCR read '{ocr_cell}'."
                )
    return None
