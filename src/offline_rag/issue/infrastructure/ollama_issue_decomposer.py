"""Issue decomposition by the local LLM on Ollama, with prompt `issue_decomposition` (ADR 0001).

Knowledge Management has its own Ollama client for page images. A context does not
import another context's adapters, so this one sends its own text request.
"""

import json
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import structlog

from offline_rag.issue.application.errors import KnowledgeTooLargeError
from offline_rag.issue.application.ports import Decomposition, KnowledgePassage
from offline_rag.issue.domain.errors import IssueFieldEmptyError
from offline_rag.issue.domain.sub_issue_candidate import Citation, SubIssueCandidate
from offline_rag.issue.infrastructure.errors import (
    DecompositionAnswerInvalidError,
    ModelUnavailableError,
    ModelUrlNotLocalError,
)
from offline_rag.issue.infrastructure.model_registry import (
    RegisteredPrompt,
    load_registered_prompt,
)

log = structlog.get_logger()

TASK = "issue_decomposition"
# Zero temperature gives the same answer again, so one retry is enough to get past
# a cut-off answer; more would only repeat it.
_MAX_ATTEMPTS = 2
# The same estimate as the approximate tokenizer of Knowledge Management.
_CHARACTERS_PER_TOKEN = 4
# Room for the chat template and the passage headers around the prompt text.
_CONTEXT_MARGIN_TOKENS = 256
_LOCAL_HOST_NAMES = {"localhost"}


class OllamaIssueDecomposer:
    """Sends the Issue and its knowledge to the LLM and reads the SubIssues it suggests."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout_s: int,
        prompts_dir: Path,
        model_manifest_path: Path,
    ) -> None:
        """Create the decomposer. The prompt is read on the first call.

        Args:
            base_url: The Ollama server, such as `http://127.0.0.1:11434`.
            timeout_s: How long one request may take, loading the model included.
            prompts_dir: The `prompts/` folder.
            model_manifest_path: The `models/manifest.yaml` file.

        Raises:
            ModelUrlNotLocalError: `base_url` is not a loopback address.
        """
        if not _is_loopback_url(base_url):
            raise ModelUrlNotLocalError(urlsplit(base_url).hostname or base_url)
        self._chat_url = base_url.rstrip("/") + "/api/chat"
        self._timeout_s = timeout_s
        self._prompts_dir = prompts_dir
        self._model_manifest_path = model_manifest_path

    def decompose(
        self, *, title: str, description: str, passages: Sequence[KnowledgePassage]
    ) -> Decomposition:
        """Return the SubIssues the LLM suggests, citing the passages they rely on.

        Raises:
            KnowledgeTooLargeError: The passages do not fit in the model's context.
            ModelRegistryUnavailableError: The prompt or its model is not registered.
            ModelUnavailableError: Ollama cannot be reached, timed out or failed.
            DecompositionAnswerInvalidError: Every answer was malformed.
        """
        prompt = load_registered_prompt(
            task=TASK, prompts_dir=self._prompts_dir, model_manifest_path=self._model_manifest_path
        )
        _check_context_fits(prompt, title, description, passages)
        text = (
            prompt.body.replace("{issue_title}", title)
            .replace("{issue_description}", description)
            .replace("{context}", format_passages(passages))
        )
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            decomposition = parse_decomposition(self._chat(prompt, text))
            if decomposition is not None:
                return decomposition
            log.warning("decomposition_answer_invalid", model=prompt.model, attempt=attempt)
        raise DecompositionAnswerInvalidError(model=prompt.model, attempts=_MAX_ATTEMPTS)

    def _chat(self, prompt: RegisteredPrompt, text: str) -> str:
        body: dict[str, Any] = {
            "model": prompt.model,
            "stream": False,
            "messages": [{"role": "user", "content": text}],
            "options": _ollama_options(prompt.params),
        }
        if "is_thinking_enabled" in prompt.params:
            body["think"] = prompt.params["is_thinking_enabled"]
        if prompt.output_schema is not None:
            body["format"] = prompt.output_schema
        request = urllib.request.Request(
            self._chat_url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
                answer: str = json.loads(response.read())["message"]["content"]
        except (urllib.error.URLError, TimeoutError, OSError, KeyError, ValueError) as error:
            raise ModelUnavailableError(prompt.model) from error
        log.info(
            "model_called",
            task=prompt.task,
            prompt_version=prompt.version,
            model=prompt.model,
            model_digest=prompt.model_digest,
            duration_s=round(time.monotonic() - started, 1),
            answer_chars=len(answer),
        )
        return answer


def format_passages(passages: Sequence[KnowledgePassage]) -> str:
    """Return the passages as the prompt's knowledge, each under the ids it is cited by."""
    return "\n\n".join(
        f"[doc_id: {passage.item_id} | page_or_section: {passage.page_or_section or '-'}]\n"
        f"{passage.text.strip()}"
        for passage in passages
    )


def parse_decomposition(answer: str) -> Decomposition | None:
    """Return the suggestions in an answer, or None when it is not the expected JSON.

    Suggestions keep the order of their `position`. A citation with an empty item
    id or quote is left out rather than failing the whole answer.
    """
    try:
        parsed = json.loads(answer)
        items = parsed["sub_issues"]
        missing = parsed.get("missing_information")
        if not isinstance(items, list) or not (missing is None or isinstance(missing, str)):
            return None
        ordered = sorted(items, key=lambda item: int(item["position"]))
        candidates = tuple(
            SubIssueCandidate(
                number=number,
                title=str(item["title"]),
                description=str(item["description"]),
                citations=_citations(item["citations"]),
            )
            for number, item in enumerate(ordered, start=1)
        )
    except (ValueError, KeyError, TypeError, AttributeError, IssueFieldEmptyError):
        return None
    return Decomposition(candidates=candidates, missing_information=(missing or "").strip() or None)


def _citations(items: Any) -> tuple[Citation, ...]:
    citations = []
    for item in items:
        try:
            citations.append(
                Citation(
                    doc_id=str(item["doc_id"]).strip(),
                    page_or_section=str(item["page_or_section"]).strip(),
                    quote=str(item["quote"]).strip(),
                )
            )
        except IssueFieldEmptyError:
            continue
    return tuple(citations)


def _check_context_fits(
    prompt: RegisteredPrompt, title: str, description: str, passages: Sequence[KnowledgePassage]
) -> None:
    context_tokens = int(prompt.params.get("context_tokens", 0))
    if not context_tokens:
        return
    limit = (
        context_tokens
        - int(prompt.params.get("max_output_tokens", 0))
        - (len(prompt.body) + len(title) + len(description)) // _CHARACTERS_PER_TOKEN
        - _CONTEXT_MARGIN_TOKENS
    )
    token_count = sum(passage.token_count for passage in passages)
    if token_count > limit:
        raise KnowledgeTooLargeError(token_count=token_count, limit_tokens=max(limit, 0))


def _is_loopback_url(url: str) -> bool:
    host = urlsplit(url).hostname or ""
    if host in _LOCAL_HOST_NAMES:
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def _ollama_options(params: dict[str, Any]) -> dict[str, Any]:
    names = {
        "temperature": "temperature",
        "seed": "seed",
        "context_tokens": "num_ctx",
        "max_output_tokens": "num_predict",
    }
    return {names[key]: value for key, value in params.items() if key in names}
