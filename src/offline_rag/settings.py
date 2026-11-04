"""Runtime settings, read from environment variables and the local `.env` file.

This is the only module allowed to read environment variables. Every field here
must also be listed in `.env.example`; a unit test checks that they match.
"""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime settings of the core. Field names map to upper-case variable names.

    Relative paths are resolved from the directory the core is started in.

    Attributes:
        data_dir: Folder for the local database and the submitted source files.
        node_registry_path: CSV file with the registered Nodes (spec §6.1).
        log_level: Lowest log level that is written.
    """

    # extra="forbid" makes a stale or misspelled variable in .env fail at startup.
    model_config = SettingsConfigDict(env_file=".env", extra="forbid")

    data_dir: Path = Path("data")
    node_registry_path: Path = Path("fixtures/registry/nodes.csv")
    log_level: Literal["debug", "info", "warning", "error"] = "info"
