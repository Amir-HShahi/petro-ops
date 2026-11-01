"""Runtime settings, read from environment variables and the local `.env` file.

This is the only module allowed to read environment variables. Every field here
must also be listed in `.env.example`; a unit test checks that they match.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime settings of the core. Field names map to upper-case variable names."""

    # extra="forbid" makes a stale or misspelled variable in .env fail at startup.
    model_config = SettingsConfigDict(env_file=".env", extra="forbid")
