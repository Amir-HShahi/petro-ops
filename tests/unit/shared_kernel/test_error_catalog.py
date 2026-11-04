import importlib
import pkgutil
import re
from pathlib import Path

import offline_rag
from offline_rag.knowledge.interface.problem_details import UNEXPECTED_CODE
from offline_rag.shared_kernel.errors import ProjectError

CATALOG_PATH = Path(__file__).parents[3] / "docs" / "errors.md"
CATALOG_ROW = re.compile(r"^\| `([A-Z0-9_]+)` \| ([^|]+) \|", re.MULTILINE)
CATEGORY_NAMES = {
    "DomainError": "Domain",
    "NotFoundError": "Not found",
    "InfrastructureError": "Infrastructure",
    "UnexpectedError": "Unexpected",
}


def _project_errors() -> list[type[ProjectError]]:
    for module in pkgutil.walk_packages(offline_rag.__path__, prefix="offline_rag."):
        importlib.import_module(module.name)

    found: list[type[ProjectError]] = []
    pending = [ProjectError]
    while pending:
        for subclass in pending.pop().__subclasses__():
            pending.append(subclass)
            if subclass.__module__.startswith("offline_rag.") and not subclass._is_category:
                found.append(subclass)
    return found


def _catalog() -> dict[str, str]:
    return {
        code: category.strip() for code, category in CATALOG_ROW.findall(CATALOG_PATH.read_text())
    }


def test_every_error_code_is_in_the_catalog_with_its_category_when_defined():
    catalog = _catalog()

    for error_class in _project_errors():
        assert catalog.get(error_class.code) == CATEGORY_NAMES[error_class.category.__name__], (
            error_class.code
        )


def test_catalog_lists_only_codes_that_exist_when_compared_with_code():
    defined_codes = {error_class.code for error_class in _project_errors()} | {UNEXPECTED_CODE}

    assert set(_catalog()) <= defined_codes


def test_unexpected_code_is_in_the_catalog_when_the_edge_sends_it():
    assert _catalog().get(UNEXPECTED_CODE) == "Unexpected"
