"""The LVM port backed by Gemma on the local Ollama server (ADR 0002)."""

import json
from typing import Any, TypeGuard

import structlog

from offline_rag.knowledge.application.ports import PageReading, PageTable
from offline_rag.knowledge.infrastructure.errors import ModelOutputInvalidError
from offline_rag.knowledge.infrastructure.model_registry import RegisteredPrompt
from offline_rag.knowledge.infrastructure.ollama_client import OllamaClient

log = structlog.get_logger()


class OllamaLvm:
    """Asks the `page_reading` prompt's model to read a page, and checks the answer's shape.

    Ollama is given the JSON Schema, but a small model can still break it, so the
    answer is checked here too and the request is repeated a few times (ADR 0001).
    """

    def __init__(
        self, *, client: OllamaClient, prompt: RegisteredPrompt, max_attempts: int
    ) -> None:
        """Create the LVM.

        Args:
            client: The local Ollama client.
            prompt: The active `page_reading` prompt and its model.
            max_attempts: How often to ask before giving up on a malformed answer.
        """
        self._client = client
        self._prompt = prompt
        self._max_attempts = max_attempts

    def read_page(self, image_png: bytes) -> PageReading:
        """Return the paragraphs and tables printed on the page.

        Raises:
            ModelUnavailableError: The model server cannot be reached.
            ModelOutputInvalidError: Every attempt gave an answer of the wrong shape.
        """
        for attempt in range(1, self._max_attempts + 1):
            answer = self._client.chat_with_image(self._prompt, image_png)
            reading = parse_page_reading(answer)
            if reading is not None:
                return reading
            log.warning(
                "model_output_invalid",
                task=self._prompt.task,
                prompt_version=self._prompt.version,
                model=self._prompt.model,
                attempt=attempt,
            )
        raise ModelOutputInvalidError(self._prompt.model, self._max_attempts)

    def release(self) -> None:
        """Unload the model from the Ollama server."""
        self._client.unload(self._prompt.model)


def parse_page_reading(answer: str) -> PageReading | None:
    """Return the reading in a `page_reading` answer, or None if it breaks the schema."""
    try:
        data = json.loads(answer)
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return None

    items: list[str | PageTable] = []
    for item in data["items"]:
        parsed = _parse_item(item)
        if parsed is None:
            return None
        items.append(parsed)
    return PageReading(items=tuple(items))


def _parse_item(item: Any) -> str | PageTable | None:
    if not isinstance(item, dict):
        return None
    kind, text = item.get("kind"), item.get("text")
    header, rows, row_labels = item.get("header"), item.get("rows"), item.get("row_labels")
    if not isinstance(text, str) or not _is_string_list(header) or not _is_string_list(row_labels):
        return None
    if not isinstance(rows, list) or not all(_is_string_list(row) for row in rows):
        return None
    if kind == "paragraph":
        return text
    if kind == "table":
        return PageTable(
            header=tuple(header),
            rows=tuple(tuple(row) for row in rows),
            row_labels=tuple(row_labels),
        )
    return None


def _is_string_list(value: Any) -> TypeGuard[list[str]]:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)
