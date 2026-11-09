"""Reads a Node registry CSV, such as `fixtures/registry/nodes.csv`, into RegisterNode commands."""

import csv
from collections.abc import Callable
from pathlib import Path

from offline_rag.organization.application.commands import RegisterNode
from offline_rag.organization.interface.errors import (
    NodeRegistryFileInvalidError,
    NodeRegistryFileNotReadableError,
)
from offline_rag.shared_kernel.confidentiality_level import ConfidentialityLevel
from offline_rag.shared_kernel.errors import DomainError
from offline_rag.shared_kernel.layer_index import LayerIndex
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

_BOOLEAN_BY_TEXT = {"true": True, "false": False}


def read_node_registry(path: Path) -> list[RegisterNode]:
    """Return one command per row, ordered from the top Layer down.

    That order registers every parent before its children, since a parent is
    always in a higher Layer.

    Raises:
        NodeRegistryFileNotReadableError: The file does not exist or cannot be read.
        NodeRegistryFileInvalidError: A row is missing a column or has a wrong value.
    """
    try:
        with path.open(newline="", encoding="utf-8") as registry:
            rows = list(csv.DictReader(registry))
    except OSError as error:
        raise NodeRegistryFileNotReadableError(path.name) from error

    commands = [_command_from_row(row, row_number) for row_number, row in enumerate(rows, 1)]
    return sorted(commands, key=lambda command: command.layer_index.value)


def _command_from_row(row: dict[str, str], row_number: int) -> RegisterNode:
    def text(column: str) -> str:
        value = row.get(column)
        if value is None:
            raise NodeRegistryFileInvalidError(row_number=row_number, column=column, value=None)
        return value.strip()

    def checked[T](column: str, parse: Callable[[str], T]) -> T:
        value = text(column)
        try:
            return parse(value)
        except (ValueError, DomainError) as error:
            raise NodeRegistryFileInvalidError(
                row_number=row_number, column=column, value=value
            ) from error

    tracked = text("is_internal_structure_tracked").lower()
    if tracked not in _BOOLEAN_BY_TEXT:
        raise NodeRegistryFileInvalidError(
            row_number=row_number, column="is_internal_structure_tracked", value=tracked
        )
    parent = text("parent_node_id")
    return RegisterNode(
        node_id=checked("node_id", NodeIdentifier),
        name=text("name"),
        layer_index=checked("layer_index", lambda value: LayerIndex(int(value))),
        parent_node_id=checked("parent_node_id", NodeIdentifier) if parent else None,
        activity_area=text("activity_area"),
        reporting_rule=text("reporting_rule"),
        confidentiality=checked("confidentiality", ConfidentialityLevel),
        is_internal_structure_tracked=_BOOLEAN_BY_TEXT[tracked],
    )
