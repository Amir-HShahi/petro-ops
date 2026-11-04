"""A minimal client for the local Ollama server, which refuses any address off this machine."""

import base64
import json
import time
import urllib.error
import urllib.request
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit

import structlog

from offline_rag.knowledge.infrastructure.errors import (
    ModelUnavailableError,
    ModelUrlNotLocalError,
)
from offline_rag.knowledge.infrastructure.model_registry import RegisteredPrompt

log = structlog.get_logger()

_LOCAL_HOST_NAMES = {"localhost"}


def is_loopback_url(url: str) -> bool:
    """Return whether `url` points at this machine (ADR 0001: no call leaves the machine)."""
    host = urlsplit(url).hostname or ""
    if host in _LOCAL_HOST_NAMES:
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


class OllamaClient:
    """Sends one chat request with one page image and returns the model's answer text."""

    def __init__(self, *, base_url: str, timeout_s: int) -> None:
        """Create the client.

        Args:
            base_url: The Ollama server, such as `http://127.0.0.1:11434`.
            timeout_s: How long one request may take. The first request also loads
                the model, which takes longer.

        Raises:
            ModelUrlNotLocalError: `base_url` is not a loopback address.
        """
        if not is_loopback_url(base_url):
            raise ModelUrlNotLocalError(urlsplit(base_url).hostname or base_url)
        self._chat_url = base_url.rstrip("/") + "/api/chat"
        self._generate_url = base_url.rstrip("/") + "/api/generate"
        self._timeout_s = timeout_s

    def chat_with_image(self, prompt: RegisteredPrompt, image_png: bytes) -> str:
        """Return the model's answer to the prompt about the image.

        Raises:
            ModelUnavailableError: The server cannot be reached, timed out or failed.
        """
        body: dict[str, Any] = {
            "model": prompt.model,
            "stream": False,
            "messages": [
                {
                    "role": "user",
                    "content": prompt.body,
                    "images": [base64.b64encode(image_png).decode("ascii")],
                }
            ],
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

    def unload(self, model: str) -> None:
        """Ask the server to free the memory of `model` now, instead of after its idle timeout.

        A failure only means the model stays loaded until Ollama's own timeout, so
        it is logged and not raised.
        """
        request = urllib.request.Request(
            self._generate_url,
            data=json.dumps({"model": model, "keep_alive": 0}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
                response.read()
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            log.warning("model_unload_failed", model=model, error=type(error).__name__)
            return
        log.debug("model_unloaded", model=model)


def _ollama_options(params: dict[str, Any]) -> dict[str, Any]:
    names = {
        "temperature": "temperature",
        "seed": "seed",
        "context_tokens": "num_ctx",
        "max_output_tokens": "num_predict",
    }
    return {names[key]: value for key, value in params.items() if key in names}
