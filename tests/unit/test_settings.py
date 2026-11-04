from pathlib import Path

import pytest
from pydantic import ValidationError

from offline_rag.settings import Settings

ENV_EXAMPLE = Path(__file__).parents[2] / ".env.example"


def _variable_names(path: Path) -> set[str]:
    lines = (line.strip() for line in path.read_text().splitlines())
    return {line.split("=", 1)[0].strip() for line in lines if line and not line.startswith("#")}


def test_env_example_lists_exactly_the_settings_fields_when_compared():
    fields = {name.upper() for name in Settings.model_fields}

    assert _variable_names(ENV_EXAMPLE) == fields


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "[::1]"])
def test_database_url_is_accepted_when_host_is_loopback(host: str):
    url = f"postgresql://user:secret@{host}:5432/petro_ops"

    assert Settings(database_url=url).database_url == url


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://user@db.example.com/petro_ops",
        "postgresql://10.0.0.5/petro_ops",
        "postgresql:///petro_ops",
    ],
)
def test_database_url_is_rejected_when_host_is_not_loopback(url: str):
    with pytest.raises(ValidationError, match="loopback"):
        Settings(database_url=url)


def test_rabbitmq_url_is_accepted_when_host_is_loopback():
    url = "amqp://user:secret@127.0.0.1:5672/%2F"

    assert Settings(rabbitmq_url=url).rabbitmq_url == url


@pytest.mark.parametrize(
    "url", ["amqp://user@broker.example.com/%2F", "amqp://10.0.0.5:5672/%2F", "amqp:///%2F"]
)
def test_rabbitmq_url_is_rejected_when_host_is_not_loopback(url: str):
    with pytest.raises(ValidationError, match="loopback"):
        Settings(rabbitmq_url=url)
