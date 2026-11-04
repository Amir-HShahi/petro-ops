"""The TableOcr port backed by glm-ocr on the local Ollama server (ADR 0002)."""

import re
from html.parser import HTMLParser

from offline_rag.knowledge.infrastructure.model_registry import RegisteredPrompt
from offline_rag.knowledge.infrastructure.ollama_client import OllamaClient

_MARKDOWN_DIVIDER = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$")


class OllamaTableOcr:
    """Asks the `table_ocr` prompt's model for the tables on a page."""

    def __init__(self, *, client: OllamaClient, prompt: RegisteredPrompt) -> None:
        """Create the OCR reader from the local client and the active `table_ocr` prompt."""
        self._client = client
        self._prompt = prompt

    def read_tables(self, image_png: bytes) -> list[list[list[str]]]:
        """Return every table on the page as rows of cells, header row first.

        Raises:
            ModelUnavailableError: The model server cannot be reached.
        """
        return parse_ocr_tables(self._client.chat_with_image(self._prompt, image_png))

    def release(self) -> None:
        """Unload the model from the Ollama server."""
        self._client.unload(self._prompt.model)


def parse_ocr_tables(answer: str) -> list[list[list[str]]]:
    """Return the tables in an OCR answer, written as HTML tables or as Markdown tables.

    A cell that spans several columns is repeated once per column, so rows keep
    the same number of columns as the header.
    """
    if "<table" in answer.lower():
        parser = _HtmlTableParser()
        parser.feed(answer)
        parser.close()
        return [table for table in parser.tables if table]
    return _markdown_tables(answer)


class _HtmlTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._colspan = 1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []
            span = dict(attrs).get("colspan") or "1"
            self._colspan = int(span) if span.isdigit() else 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.extend([" ".join("".join(self._cell).split())] * self._colspan)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.tables[-1].append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def _markdown_tables(answer: str) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    current: list[list[str]] = []
    for line in [*answer.splitlines(), ""]:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            if not _MARKDOWN_DIVIDER.match(stripped):
                current.append([cell.strip() for cell in stripped.strip("|").split("|")])
        elif current:
            tables.append(current)
            current = []
    return tables
