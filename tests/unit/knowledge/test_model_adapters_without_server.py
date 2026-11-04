import base64
import io
import json
import urllib.error
from typing import Any

import pytest
from structlog.testing import capture_logs

from offline_rag.knowledge.application.ports import PageReading, PageTable
from offline_rag.knowledge.infrastructure.errors import (
    ModelOutputInvalidError,
    ModelUnavailableError,
    ModelUrlNotLocalError,
)
from offline_rag.knowledge.infrastructure.model_registry import RegisteredPrompt
from offline_rag.knowledge.infrastructure.ollama_client import OllamaClient, is_loopback_url
from offline_rag.knowledge.infrastructure.ollama_lvm import OllamaLvm, parse_page_reading
from offline_rag.knowledge.infrastructure.ollama_table_ocr import OllamaTableOcr, parse_ocr_tables

PAGE_READING_PROMPT = RegisteredPrompt(
    task="page_reading",
    version=1,
    body="Read the page.",
    model="gemma4:12b-it-qat",
    model_digest="38044be4f923",
    params={
        "temperature": 0,
        "seed": 42,
        "is_thinking_enabled": False,
        "context_tokens": 8192,
        "max_output_tokens": 4096,
    },
    output_schema={"type": "object"},
)
PARAGRAPH_ITEM = {
    "kind": "paragraph",
    "text": "Coating in good condition.",
    "header": [],
    "rows": [],
    "row_labels": [],
}
TABLE_ITEM = {
    "kind": "table",
    "text": "",
    "header": ["Location", "mm"],
    "rows": [["EL +8.5 m", "21.0"]],
    "row_labels": ["EL +8.5 m"],
}
VALID_ANSWER = json.dumps({"items": [TABLE_ITEM, PARAGRAPH_ITEM]})


@pytest.mark.parametrize(
    ("url", "is_local"),
    [
        ("http://127.0.0.1:11434", True),
        ("http://localhost:11434", True),
        ("http://[::1]:11434", True),
        ("http://127.8.0.1:11434", True),
        ("http://192.168.1.20:11434", False),
        ("https://ollama.example.com", False),
        ("http://0.0.0.0:11434", False),
    ],
)
def test_only_this_machine_counts_as_local_when_url_is_checked(url: str, is_local: bool):
    assert is_loopback_url(url) is is_local


def test_client_refuses_to_start_when_server_is_not_on_this_machine():
    with pytest.raises(ModelUrlNotLocalError) as caught:
        OllamaClient(base_url="http://10.0.0.5:11434", timeout_s=5)

    assert caught.value.details == {"host": "10.0.0.5"}


class _FakeResponse(io.BytesIO):
    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def test_request_carries_image_schema_and_model_options_when_page_is_sent(
    monkeypatch: pytest.MonkeyPatch,
):
    sent: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: int) -> _FakeResponse:
        sent.update(url=request.full_url, timeout=timeout, body=json.loads(request.data))
        return _FakeResponse(json.dumps({"message": {"content": "answer"}}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = OllamaClient(base_url="http://127.0.0.1:11434/", timeout_s=30)

    answer = client.chat_with_image(PAGE_READING_PROMPT, b"PNG bytes")

    assert answer == "answer"
    assert sent["url"] == "http://127.0.0.1:11434/api/chat"
    assert sent["timeout"] == 30
    body = sent["body"]
    assert body["model"] == "gemma4:12b-it-qat"
    assert body["think"] is False
    assert body["format"] == {"type": "object"}
    assert body["options"] == {"temperature": 0, "seed": 42, "num_ctx": 8192, "num_predict": 4096}
    assert base64.b64decode(body["messages"][0]["images"][0]) == b"PNG bytes"


def test_model_unavailable_is_raised_when_server_cannot_be_reached(monkeypatch: pytest.MonkeyPatch):
    def refuse(request: Any, timeout: int) -> None:
        reason = "connection refused"
        raise urllib.error.URLError(reason)

    monkeypatch.setattr("urllib.request.urlopen", refuse)
    client = OllamaClient(base_url="http://127.0.0.1:11434", timeout_s=5)

    with pytest.raises(ModelUnavailableError) as caught:
        client.chat_with_image(PAGE_READING_PROMPT, b"PNG")

    assert caught.value.details == {"model": "gemma4:12b-it-qat"}


def test_page_reading_keeps_the_page_order_when_answer_matches_the_schema():
    assert parse_page_reading(VALID_ANSWER) == PageReading(
        items=(
            PageTable(
                header=("Location", "mm"), rows=(("EL +8.5 m", "21.0"),), row_labels=("EL +8.5 m",)
            ),
            "Coating in good condition.",
        ),
    )


@pytest.mark.parametrize(
    "answer",
    [
        "not json",
        "[]",
        json.dumps({"items": "one string"}),
        json.dumps({"items": [{**TABLE_ITEM, "rows": [[1, 2]]}]}),
        json.dumps(
            {"items": [{key: value for key, value in TABLE_ITEM.items() if key != "row_labels"}]}
        ),
        json.dumps({"items": [{**PARAGRAPH_ITEM, "kind": "figure"}]}),
    ],
    ids=[
        "not-json",
        "not-object",
        "items-not-list",
        "number-cells",
        "no-row-labels",
        "unknown-kind",
    ],
)
def test_page_reading_is_rejected_when_answer_breaks_the_schema(answer: str):
    assert parse_page_reading(answer) is None


class _ScriptedClient:
    def __init__(self, answers: list[str]) -> None:
        self._answers = answers
        self.calls = 0

    def chat_with_image(self, prompt: RegisteredPrompt, image_png: bytes) -> str:
        self.calls += 1
        return self._answers.pop(0)


def test_lvm_asks_again_when_first_answer_is_malformed():
    client = _ScriptedClient(["{broken", VALID_ANSWER])
    lvm = OllamaLvm(client=client, prompt=PAGE_READING_PROMPT, max_attempts=2)  # type: ignore[arg-type]

    reading = lvm.read_page(b"PNG")

    assert client.calls == 2
    assert reading.items[1] == "Coating in good condition."


def test_lvm_gives_up_when_every_answer_is_malformed():
    client = _ScriptedClient(["{broken", "still broken"])
    lvm = OllamaLvm(client=client, prompt=PAGE_READING_PROMPT, max_attempts=2)  # type: ignore[arg-type]

    with pytest.raises(ModelOutputInvalidError) as caught:
        lvm.read_page(b"PNG")

    assert caught.value.details == {"model": "gemma4:12b-it-qat", "attempts": 2}


def test_html_tables_are_parsed_with_spanned_cells_repeated_when_ocr_answers_in_html():
    answer = (
        "<table><tr><th>Location</th><th>Measured\n(mm)</th></tr>"
        '<tr><td colspan="2">Splash zone</td></tr>'
        "<tr><td>EL +8.5 m</td><td>21.0</td></tr></table>\n"
        "<table><tr><td>Field</td><td>Value</td></tr></table>"
    )

    assert parse_ocr_tables(answer) == [
        [["Location", "Measured (mm)"], ["Splash zone", "Splash zone"], ["EL +8.5 m", "21.0"]],
        [["Field", "Value"]],
    ]


def test_markdown_tables_are_parsed_without_the_divider_when_ocr_answers_in_markdown():
    answer = (
        "Readings\n| Location | mm |\n|---|:---:|\n| EL +8.5 m | 21.0 |\n\nText after.\n| A | B |"
    )

    assert parse_ocr_tables(answer) == [[["Location", "mm"], ["EL +8.5 m", "21.0"]], [["A", "B"]]]


def test_no_tables_are_found_when_ocr_answer_is_plain_text():
    assert parse_ocr_tables("No table on this page.") == []


def test_unload_asks_ollama_to_free_the_model_now_when_released(monkeypatch: pytest.MonkeyPatch):
    sent: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: int) -> _FakeResponse:
        sent.update(url=request.full_url, body=json.loads(request.data))
        return _FakeResponse(b"{}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    OllamaClient(base_url="http://127.0.0.1:11434", timeout_s=5).unload("glm-ocr:latest")

    assert sent == {
        "url": "http://127.0.0.1:11434/api/generate",
        "body": {"model": "glm-ocr:latest", "keep_alive": 0},
    }


def test_unload_failure_is_only_logged_when_server_is_gone(monkeypatch: pytest.MonkeyPatch):
    def refuse(request: Any, timeout: int) -> None:
        reason = "connection refused"
        raise urllib.error.URLError(reason)

    monkeypatch.setattr("urllib.request.urlopen", refuse)

    with capture_logs() as logs:
        OllamaClient(base_url="http://127.0.0.1:11434", timeout_s=5).unload("glm-ocr:latest")

    assert logs == [
        {
            "event": "model_unload_failed",
            "log_level": "warning",
            "model": "glm-ocr:latest",
            "error": "URLError",
        }
    ]


class _UnloadRecorder:
    def __init__(self) -> None:
        self.unloaded: list[str] = []

    def unload(self, model: str) -> None:
        self.unloaded.append(model)


def test_each_model_adapter_unloads_its_own_model_when_released():
    client = _UnloadRecorder()
    ocr_prompt = RegisteredPrompt(
        task="table_ocr",
        version=1,
        body="Table Recognition:",
        model="glm-ocr:latest",
        model_digest="89d735dd9c07",
        params={},
        output_schema=None,
    )

    OllamaLvm(client=client, prompt=PAGE_READING_PROMPT, max_attempts=1).release()  # type: ignore[arg-type]
    OllamaTableOcr(client=client, prompt=ocr_prompt).release()  # type: ignore[arg-type]

    assert client.unloaded == ["gemma4:12b-it-qat", "glm-ocr:latest"]
