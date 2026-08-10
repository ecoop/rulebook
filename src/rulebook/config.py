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
    embedding_model: str = "voyage-4"
    claude_model: str = "claude-sonnet-5"

    # --- Storage -----------------------------------------------------------
    # Where the vector index lives on the local filesystem. Local dev leaves
    # this relative (resolved under repo_root); a hosted container sets an
    # absolute INDEX_PATH (e.g. /tmp/rulebook/index) that index_sync.py
    # populates from GCS at startup — repo_root is unwritable there.
    index_path: Path = Field(default=Path("./data/index"))

    # Writable root for app-owned mutable scratch (cost counter JSON when
    # local, JSONL logs). Defaults to <repo>/data for dev. Hosted deploys
    # point RULEBOOK_DATA_DIR at a writable location (e.g. /tmp/rulebook)
    # because the installed-package repo_root resolves into an unwritable
    # site-packages ancestor. Durable state (cost counter) still routes
    # through the GCS StateBackend; only transient scratch lives here.
    data_root: Path | None = Field(
        default=None,
        validation_alias="RULEBOOK_DATA_DIR",
    )

    # --- Guardrails (llm-cost-governor library) ---------------------------
    # Master gate. When False the CostCounter and IP rate limit are
    # constructed but disabled — no enforcement, no persistence. Local
    # dev leaves this off; hosted deployments flip it on.
    guardrails_enabled: bool = False

    # State backend for the cost counter. "local" writes JSON under
    # data/; "gcs" (deferred until we host) writes to a bucket.
    state_backend_kind: str = Field(default="local", pattern="^(local|gcs)$")
    gcs_state_bucket: str | None = None

    # Rolling-window cost caps in USD. Defaults match pitchcraft's.
    # A single call over any cap raises; alert fires. Tune per audience
    # once we know real usage patterns.
    cap_hourly_usd: float = 0.50
    cap_daily_usd: float = 2.00
    cap_weekly_usd: float = 10.00
    cap_per_token_usd: float = 1.00

    # IP-based rate limit in requests per minute. Applied to /ask via a
    # FastAPI dependency. Only enforced when guardrails_enabled=True.
    rate_limit_rpm: int = 30

    # --- Guest auth (guest-auth library) ----------------------------------
    # Opt-in invite-token gate for pre-production demos. When demo_mode
    # is False the middleware is a complete pass-through — local dev
    # and any public deploy without an allowlist keep the current
    # no-auth behaviour. Field names (demo_mode, invite_tokens) match
    # the GuestAuthConfig Protocol so the Settings instance can be
    # handed to InviteAuthMiddleware(config=...) directly.
    demo_mode: bool = Field(
        default=False,
        validation_alias="RULEBOOK_DEMO_MODE",
    )
    # JSON map of {token: recipient-label}. Read at request time from
    # this attribute, so tests can monkeypatch it on the live app.
    # Mint tokens with any opaque generator (e.g. `uuidgen`) prefixed
    # with `tok_` for readability, then set:
    #   RULEBOOK_INVITE_TOKENS='{"tok_abc123": "eric-test"}'
    invite_tokens: dict[str, str] = Field(
        default_factory=dict,
        validation_alias="RULEBOOK_INVITE_TOKENS",
    )

    @property
    def repo_root(self) -> Path:
        # Anchor relative paths to the repo root, not the shell's cwd, so
        # `uv run` and Jupyter both resolve `./data/index` the same way.
        return Path(__file__).resolve().parents[2]

    @property
    def resolved_index_path(self) -> Path:
        p = self.index_path
        return p if p.is_absolute() else self.repo_root / p

    @property
    def data_dir(self) -> Path:
        """Root of app-owned mutable state — cost counter JSON, JSONL logs, etc.

        Defaults to a subdir of the repo, matching how the rest of the app
        already writes to ``data/`` in local dev. Hosted deploys override via
        RULEBOOK_DATA_DIR (``data_root``) to a writable path, because the
        installed-package ``repo_root`` resolves to an unwritable
        site-packages ancestor. Durable state routes through the GCS
        StateBackend; this is scratch.
        """
        if self.data_root is not None:
            return (
                self.data_root
                if self.data_root.is_absolute()
                else self.repo_root / self.data_root
            )
        return self.repo_root / "data"


# Singleton — every other module imports this and never re-instantiates.
settings = Settings()  # type: ignore[call-arg]
