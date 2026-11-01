from pathlib import Path

from offline_rag.settings import Settings

ENV_EXAMPLE = Path(__file__).parents[2] / ".env.example"


def _variable_names(path: Path) -> set[str]:
    lines = (line.strip() for line in path.read_text().splitlines())
    return {line.split("=", 1)[0].strip() for line in lines if line and not line.startswith("#")}


def test_env_example_lists_exactly_the_settings_fields_when_compared():
    fields = {name.upper() for name in Settings.model_fields}

    assert _variable_names(ENV_EXAMPLE) == fields
