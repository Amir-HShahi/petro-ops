from pathlib import Path
from typing import Any

import yaml

MANIFEST_PATH = Path(__file__).parents[2] / "models" / "manifest.yaml"
ROLES = {"llm", "embedding", "lvm", "reranker"}
STATUSES = {"chosen", "deferred"}
CHOSEN_FIELDS = {"name", "tag", "runtime", "source"}


def _models() -> list[dict[str, Any]]:
    models: list[dict[str, Any]] = yaml.safe_load(MANIFEST_PATH.read_text())["models"]
    return models


def test_every_role_is_listed_once_when_loaded():
    roles = [model["role"] for model in _models()]

    assert sorted(roles) == sorted(ROLES)


def test_models_use_known_statuses_when_loaded():
    assert {model["status"] for model in _models()} <= STATUSES


def test_chosen_models_say_how_to_get_them_when_loaded():
    chosen = [model for model in _models() if model["status"] == "chosen"]

    for model in chosen:
        missing = {field for field in CHOSEN_FIELDS if not model.get(field)}
        assert not missing, f"{model['role']} is missing {missing}"


def test_llm_default_params_fit_the_model_when_chosen():
    llm = next(model for model in _models() if model["role"] == "llm")
    params = llm["default_params"]

    assert params["temperature"] == 0
    assert isinstance(params["seed"], int)
    assert params["max_output_tokens"] < params["context_tokens"]
    if llm["context_tokens"]:
        assert params["context_tokens"] <= llm["context_tokens"]


def test_embedding_model_has_its_limits_when_chosen():
    embedding = next(model for model in _models() if model["role"] == "embedding")

    assert embedding["status"] == "chosen"
    assert embedding["context_tokens"] > 0
    assert embedding["dimensions"] > 0
