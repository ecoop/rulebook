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
    # no-auth behaviour. `demo_mode` + the `invite_tokens` property match
    # the GuestAuthConfig Protocol so the Settings instance can be handed
    # to InviteAuthMiddleware(config=...) directly.
    demo_mode: bool = Field(
        default=False,
        validation_alias="RULEBOOK_DEMO_MODE",
    )
    # Static seed of {token: recipient-label}. The historical env var —
    # still the whole allowlist in local dev. Mint tokens with any opaque
    # generator (e.g. `uuidgen`) prefixed with `tok_`, then set:
    #   RULEBOOK_INVITE_TOKENS='{"tok_abc123": "eric-test"}'
    # A hosted (gcs) deploy layers a mutable GCS object OVER this seed —
    # see the `invite_tokens` property and tokens.py.
    invite_tokens_seed: dict[str, str] = Field(
        default_factory=dict,
        validation_alias="RULEBOOK_INVITE_TOKENS",
    )
    # Name of the GCS object (in gcs_state_bucket) holding the mutable
    # allowlist. Read per request with a short TTL when state_backend_kind
    # is "gcs"; ignored otherwise. Adding a user = rewriting this object,
    # no redeploy (see scripts/invite_tokens.py).
    invite_tokens_object: str = Field(
        default="invite_tokens.json",
        validation_alias="RULEBOOK_INVITE_TOKENS_OBJECT",
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
    def invite_tokens(self) -> dict[str, str]:
        """Effective {token: recipient-label} allowlist for guest-auth.

        Local dev: just ``invite_tokens_seed``. Hosted (gcs): the seed with
        the mutable GCS object merged over it, refreshed on a short TTL so a
        newly-added user works within seconds and no redeploy is needed.
        Read per request by InviteAuthMiddleware (only when demo_mode is on).
        """
        from .tokens import get_invite_tokens

        return get_invite_tokens(
            kind=self.state_backend_kind,
            bucket=self.gcs_state_bucket,
            object_name=self.invite_tokens_object,
            seed=self.invite_tokens_seed,
        )

    @property
    def rules_dir(self) -> Path:
        """Source rulebooks (rules/<sport>/…), read by diagnostics + admin.

        ``repo_root/rules`` in local dev. In an installed-package container
        ``repo_root`` points into an unwritable site-packages ancestor with
        no ``rules/``; the image ships the sources under ``WORKDIR=/app``,
        so fall back to the CWD-relative ``rules/`` — same trick main.py
        uses for ``web/dist``.
        """
        candidate = self.repo_root / "rules"
        return candidate if candidate.is_dir() else Path("rules").resolve()

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
