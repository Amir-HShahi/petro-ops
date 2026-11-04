"""Runtime settings, read from environment variables and the local `.env` file.

This is the only module allowed to read environment variables. Every field here
must also be listed in `.env.example`; a unit test checks that they match.
"""

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import PositiveInt, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class Settings(BaseSettings):
    """All runtime settings of the core. Field names map to upper-case variable names.

    Relative paths are resolved from the directory the core is started in.

    Attributes:
        data_dir: Folder for the submitted source files.
        database_url: The local Postgres server as a libpq URL. Only loopback hosts
            are accepted (ADR 0005).
        database_pool_size: The most database connections one process keeps open.
        database_connect_timeout_s: How long to wait for a database connection, in seconds.
        reconcile_after_s: How long a queued ingestion may wait after its last message,
            in seconds, before the reconciler sends a new one (ADR 0005).
        rabbitmq_url: The local RabbitMQ broker as an AMQP URL. Only loopback hosts
            are accepted (ADR 0005).
        worker_prefetch_count: How many unacked messages one worker holds at once.
        worker_max_attempts: How many times a worker step is tried before its
            ingestion fails and the message goes to the dead-letter queue.
        worker_retry_delay_s: How long a failed step waits in the retry queue, in seconds.
        node_registry_path: CSV file with the registered Nodes (spec §6.1).
        log_level: Lowest log level that is written.
        min_page_text_chars: A PDF page with fewer non-space characters than this
            has no usable text layer and is left for the LVM.
        libreoffice_path: The LibreOffice `soffice` program that converts DOC files,
            as a name on PATH or a full path.
        doc_conversion_timeout_s: How long one DOC conversion may take, in seconds.
        ollama_url: The local Ollama server. Only loopback addresses are accepted.
        model_timeout_s: How long one model request may take, in seconds. The first
            request also loads the model.
        page_render_dpi: Resolution of page images for the vision models.
        lvm_max_attempts: How often the LVM is asked before a malformed answer fails.
        prompts_dir: The folder with the prompt registry and templates.
        model_manifest_path: The file that names the model of each role.
    """

    # extra="forbid" makes a stale or misspelled variable in .env fail at startup.
    model_config = SettingsConfigDict(env_file=".env", extra="forbid")

    data_dir: Path = Path("data")
    database_url: str = "postgresql://petro_ops:petro_ops@127.0.0.1:5432/petro_ops"
    database_pool_size: PositiveInt = 5
    database_connect_timeout_s: PositiveInt = 5
    reconcile_after_s: PositiveInt = 1800
    rabbitmq_url: str = "amqp://petro_ops:petro_ops@127.0.0.1:5672/%2F"
    worker_prefetch_count: PositiveInt = 1
    worker_max_attempts: PositiveInt = 3
    worker_retry_delay_s: PositiveInt = 30
    node_registry_path: Path = Path("fixtures/registry/nodes.csv")
    log_level: Literal["debug", "info", "warning", "error"] = "info"
    min_page_text_chars: PositiveInt = 20
    libreoffice_path: str = "soffice"
    doc_conversion_timeout_s: PositiveInt = 120
    ollama_url: str = "http://127.0.0.1:11434"
    model_timeout_s: PositiveInt = 300
    page_render_dpi: PositiveInt = 150
    lvm_max_attempts: PositiveInt = 2
    prompts_dir: Path = Path("prompts")
    model_manifest_path: Path = Path("models/manifest.yaml")

    @field_validator("database_url", "rabbitmq_url")
    @classmethod
    def _require_loopback_host(cls, url: str) -> str:
        # The core is offline: every socket must stay on this machine (ADR 0005).
        host = urlsplit(url).hostname
        if host not in LOOPBACK_HOSTS:
            message = f"must point to a loopback host ({', '.join(sorted(LOOPBACK_HOSTS))})"
            raise ValueError(message)
        return url
