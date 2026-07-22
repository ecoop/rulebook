"""Configuration loaded from environment variables.

Every knob — API keys, model choices, storage path — lives here so the
rest of the code can stay ignorant of where these values come from. That
matters for two reasons:

    1. You can swap providers or models by editing .env, without touching
       any pipeline code.
    2. Tests can construct a Settings object with different values instead
       of monkeypatching os.environ.

We use pydantic-settings so a missing required key blows up loudly at
import time, rather than deep inside the first API call.
"""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- API keys ----------------------------------------------------------
    anthropic_api_key: str = Field(..., description="Required. For generation.")
    voyage_api_key: str | None = None
    openai_api_key: str | None = None

    # --- Provider / model selection ---------------------------------------
    embedding_provider: str = Field(default="voyage", pattern="^(voyage|openai)$")
    embedding_model: str = "voyage-3.5"
    claude_model: str = "claude-sonnet-5"

    # --- Storage -----------------------------------------------------------
    index_path: Path = Field(default=Path("./data/index"))

    @property
    def repo_root(self) -> Path:
        # Anchor relative paths to the repo root, not the shell's cwd, so
        # `uv run` and Jupyter both resolve `./data/index` the same way.
        return Path(__file__).resolve().parents[2]

    @property
    def resolved_index_path(self) -> Path:
        p = self.index_path
        return p if p.is_absolute() else self.repo_root / p


# Singleton — every other module imports this and never re-instantiates.
settings = Settings()  # type: ignore[call-arg]
