import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).parents[3]
PROMPTS_DIR = ROOT / "prompts"
REGISTRY_PATH = PROMPTS_DIR / "registry.yaml"
RUBRICS_DIR = PROMPTS_DIR / "rubrics"
MANIFEST_PATH = ROOT / "models" / "manifest.yaml"
OUTPUT_FORMATS = {"text", "json"}
CITES_SOURCES = {"required", "none"}
FRONT_MATTER_FIELDS = {"id", "version", "model", "variables", "changelog"}
PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


def _tasks() -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = yaml.safe_load(REGISTRY_PATH.read_text())["tasks"]
    return tasks


def _models_by_role() -> dict[str, dict[str, Any]]:
    models = yaml.safe_load(MANIFEST_PATH.read_text())["models"]
    return {model["role"]: model for model in models}


def _split_prompt(path: Path) -> tuple[dict[str, Any], str]:
    _, front_matter, body = path.read_text().split("---\n", 2)
    return yaml.safe_load(front_matter), body


def _active_prompt_path(task: dict[str, Any]) -> Path:
    return PROMPTS_DIR / task["task"] / f"v{task['active_version']}.md"


TASK_IDS = [task["task"] for task in _tasks()]


def test_task_names_are_unique_when_loaded():
    assert len(TASK_IDS) == len(set(TASK_IDS))


@pytest.mark.parametrize("task", _tasks(), ids=TASK_IDS)
def test_active_prompt_file_exists_when_registered(task: dict[str, Any]):
    assert _active_prompt_path(task).is_file()


@pytest.mark.parametrize("task", _tasks(), ids=TASK_IDS)
def test_prompt_front_matter_matches_registry_when_loaded(task: dict[str, Any]):
    front_matter, _ = _split_prompt(_active_prompt_path(task))

    assert set(front_matter) == FRONT_MATTER_FIELDS
    assert front_matter["id"] == task["task"]
    assert front_matter["version"] == task["active_version"]


@pytest.mark.parametrize("task", _tasks(), ids=TASK_IDS)
def test_placeholders_match_declared_variables_when_loaded(task: dict[str, Any]):
    front_matter, body = _split_prompt(_active_prompt_path(task))

    assert set(PLACEHOLDER.findall(body)) == set(front_matter["variables"])


@pytest.mark.parametrize("task", _tasks(), ids=TASK_IDS)
def test_prompt_renders_without_leftover_braces_when_all_variables_given(task: dict[str, Any]):
    front_matter, body = _split_prompt(_active_prompt_path(task))

    rendered = body.format_map(dict.fromkeys(front_matter["variables"], "x"))

    assert "{" not in rendered
    assert "}" not in rendered


@pytest.mark.parametrize("task", _tasks(), ids=TASK_IDS)
def test_output_format_is_known_when_registered(task: dict[str, Any]):
    assert task["output_format"] in OUTPUT_FORMATS
    assert task["cites_sources"] in CITES_SOURCES


@pytest.mark.parametrize("task", _tasks(), ids=TASK_IDS)
def test_json_tasks_have_an_object_schema_when_registered(task: dict[str, Any]):
    if task["output_format"] != "json":
        pytest.skip("text output has no schema")

    schema = json.loads((ROOT / task["output_schema"]).read_text())

    assert schema["type"] == "object"
    assert schema["required"]


@pytest.mark.parametrize("task", _tasks(), ids=TASK_IDS)
def test_model_role_is_a_chosen_model_when_registered(task: dict[str, Any]):
    model = _models_by_role().get(task["model_role"])

    assert model is not None
    assert model["status"] == "chosen"


@pytest.mark.parametrize("task", _tasks(), ids=TASK_IDS)
def test_params_only_override_known_defaults_when_registered(task: dict[str, Any]):
    defaults = _models_by_role()[task["model_role"]]["default_params"]

    assert set(task["params"]) <= set(defaults)


@pytest.mark.parametrize("task", _tasks(), ids=TASK_IDS)
def test_judge_rubric_exists_when_set(task: dict[str, Any]):
    if task["judge_rubric"] == "none":
        pytest.skip("task is not judged")

    assert (RUBRICS_DIR / f"{task['judge_rubric']}.yaml").is_file()


@pytest.mark.parametrize("path", sorted(RUBRICS_DIR.glob("*.yaml")), ids=lambda path: path.stem)
def test_rubric_points_add_up_to_max_score_when_loaded(path: Path):
    rubric = yaml.safe_load(path.read_text())

    assert rubric["name"] == path.stem
    assert sum(criterion["points"] for criterion in rubric["criteria"]) == rubric["max_score"]
    assert 0 < rubric["pass_score"] <= rubric["max_score"]


def test_llm_judge_max_score_matches_default_rubric_when_loaded():
    schema = json.loads((PROMPTS_DIR / "llm_judge" / "schema.json").read_text())
    rubric = yaml.safe_load((RUBRICS_DIR / "default.yaml").read_text())

    assert schema["properties"]["score"]["maximum"] == rubric["max_score"]
