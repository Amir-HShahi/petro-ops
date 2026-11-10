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


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_api_host_is_accepted_when_it_is_loopback(host: str):
    assert Settings(api_host=host).api_host == host


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "api.example.com"])
def test_api_host_is_rejected_when_it_is_not_loopback(host: str):
    with pytest.raises(ValidationError, match="loopback"):
        Settings(api_host=host)


@pytest.mark.parametrize("port", [0, 65536])
def test_api_port_is_rejected_when_out_of_range(port: int):
    with pytest.raises(ValidationError):
        Settings(api_port=port)


def test_rabbitmq_management_url_is_rejected_when_host_is_not_loopback():
    with pytest.raises(ValidationError, match="loopback"):
        Settings(rabbitmq_management_url="http://user:secret@mq.example.com:15672")


def test_chunk_and_overlap_defaults_are_accepted_when_nothing_is_set():
    settings = Settings()

    assert (settings.chunk_target_tokens, settings.chunk_max_tokens) == (400, 512)
    assert settings.overlap_ambiguous_from_similarity < settings.overlap_chunk_similarity


def test_chunk_max_tokens_is_rejected_when_it_is_below_the_target():
    with pytest.raises(ValidationError, match="chunk_max_tokens"):
        Settings(chunk_target_tokens=500, chunk_max_tokens=400)


def test_chunk_max_tokens_is_rejected_when_it_reaches_the_embedding_context():
    with pytest.raises(ValidationError):
        Settings(chunk_max_tokens=2048)


@pytest.mark.parametrize("share", [-0.1, 0.51])
def test_chunk_overlap_share_is_rejected_when_out_of_range(share: float):
    with pytest.raises(ValidationError):
        Settings(chunk_overlap_share=share)


@pytest.mark.parametrize(
    "field",
    ["overlap_chunk_similarity", "overlap_ambiguous_from_similarity", "overlap_min_chunk_share"],
)
@pytest.mark.parametrize("value", [0, 1.01])
def test_overlap_share_is_rejected_when_out_of_range(field: str, value: float):
    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_ambiguous_band_is_rejected_when_it_starts_at_the_overlap_threshold():
    with pytest.raises(ValidationError, match="overlap_ambiguous_from_similarity"):
        Settings(overlap_chunk_similarity=0.4, overlap_ambiguous_from_similarity=0.4)


def test_duplicate_shingle_words_is_rejected_when_zero():
    with pytest.raises(ValidationError):
        Settings(duplicate_shingle_words=0)
