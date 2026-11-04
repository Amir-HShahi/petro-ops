"""The active prompt of a task and the model it runs on, read from the repository's registries.

`prompts/registry.yaml` names the active version and the model role of each task,
and `models/manifest.yaml` names the model of each role. This loader moves to the
Model and Prompt context when that context gets code (phase 14).
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from offline_rag.knowledge.infrastructure.errors import ModelRegistryUnavailableError


@dataclass(frozen=True, kw_only=True)
class RegisteredPrompt:
    """The active prompt of one task, with everything needed to call its model.

    Attributes:
        task: The task name, such as `page_reading`.
        version: The active prompt version.
        body: The prompt text sent to the model, without its front matter.
        model: The model as Ollama names it, such as `gemma4:12b-it-qat`.
        model_digest: The digest of the tested weights, for the logs.
        params: The model's default parameters with the task's overrides applied.
        output_schema: The JSON Schema of a JSON task, or None for a text task.
    """

    task: str
    version: int
    body: str
    model: str
    model_digest: str
    params: dict[str, Any]
    output_schema: dict[str, Any] | None


def load_registered_prompt(
    *, task: str, prompts_dir: Path, model_manifest_path: Path
) -> RegisteredPrompt:
    """Return the active prompt of `task` and its model.

    Args:
        task: The task name in `prompts/registry.yaml`.
        prompts_dir: The `prompts/` folder.
        model_manifest_path: The `models/manifest.yaml` file.

    Raises:
        ModelRegistryUnavailableError: A file is missing, or the task or its model
            role is not registered.
    """
    try:
        registry = yaml.safe_load((prompts_dir / "registry.yaml").read_text(encoding="utf-8"))
        entry = next(entry for entry in registry["tasks"] if entry["task"] == task)
        manifest = yaml.safe_load(model_manifest_path.read_text(encoding="utf-8"))
        model = next(
            model
            for model in manifest["models"]
            if model["role"] == entry["model_role"] and model["status"] == "chosen"
        )
        version = int(entry["active_version"])
        prompt_text = (prompts_dir / task / f"v{version}.md").read_text(encoding="utf-8")
        _, _front_matter, body = prompt_text.split("---\n", 2)
        schema_path = entry.get("output_schema")
        output_schema = (
            json.loads((prompts_dir.parent / schema_path).read_text(encoding="utf-8"))
            if schema_path
            else None
        )
    except (OSError, KeyError, StopIteration, ValueError, yaml.YAMLError) as error:
        raise ModelRegistryUnavailableError(task) from error

    return RegisteredPrompt(
        task=task,
        version=version,
        body=body.strip(),
        model=f"{model['name']}:{model['tag']}",
        model_digest=str(model.get("digest") or ""),
        params={**model.get("default_params", {}), **(entry.get("params") or {})},
        output_schema=output_schema,
    )
