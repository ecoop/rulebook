"""Singleton facade for llm-guardrails — see docs/integration.md in that repo.

Every consumer that needs the cost counter or the rate-limit dependency
imports from THIS module (``from rulebook import app_state``), never
from ``llm_guardrails.*`` directly. Constructed once at server start
via ``initialize()``; all module-level names become non-None after
that call.

Pitchcraft's integration guide places this file at the repo root; we
put it inside the ``rulebook`` package so scripts and CLI entry points
that run from any directory can import it without sys.path fiddling.
Semantics are identical — one instance per process — and pitchcraft's
init-order pattern still applies.

FASTAPI INIT-ORDER GOTCHA

    Routers that call ``Depends(app_state.enforce_ip_rate_limit)`` grab
    the reference at import time — BEFORE ``initialize()`` runs. If the
    dependency were a name assigned inside ``initialize()``, Depends
    would snapshot ``None`` and no runtime setup would fix it. The
    workaround: ``enforce_ip_rate_limit`` is defined here as a stable
    wrapper function that looks up a lazily-set implementation callable.

    api/main.py must call ``app_state.initialize(...)`` at the top of
    the module, BEFORE any router or Depends() usage. Since rulebook
    has a single-file API (no separate router modules), the ordering
    inside api/main.py is enough.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import Request

from llm_guardrails.counters import CostCounter
from llm_guardrails.fastapi_ext import make_enforce_ip_rate_limit
from llm_guardrails.ratelimit import IPRateLimiter
from llm_guardrails.state import StateBackend, get_backend

from .config import Settings


class ProviderTotalsHook:
    """Guardrails hook that maintains in-memory per-provider USD totals.

    Sits alongside WindowedCapHook in each call site's hook chain.
    Records ``usage.cost_usd`` against ``usage.provider`` after every
    LLM call so the Usage widget can break spend out per provider
    (anthropic vs voyage), which the shared CostCounter aggregates away.

    Deliberately in-memory only — resets on process restart. If we want
    persistence later, swap the impl to read from a persisted event log
    (see the roadmap discussion in the "Voyage on the Usage widget"
    exchange). The public shape (``totals: dict[str, float]``) stays
    the same across that swap.
    """

    def __init__(self, totals: dict[str, float]):
        self._totals = totals

    def pre(self, ctx: Any) -> None:  # noqa: D401 — Hook protocol
        return None

    def post(self, ctx: Any, usage: Any) -> None:
        provider = getattr(usage, "provider", None) or "unknown"
        usd = float(getattr(usage, "cost_usd", 0.0) or 0.0)
        self._totals[provider] = self._totals.get(provider, 0.0) + usd

# Module-level singletons, populated by initialize().
cost_counter: Optional[CostCounter] = None
ip_rate_limiter: Optional[IPRateLimiter] = None
state_backend: Optional[StateBackend] = None
_enforce_ip_rate_limit_impl: Optional[Callable[[Request], None]] = None

# Per-provider running totals — mutated in place by ProviderTotalsHook
# on every LLM call. Readers (e.g. the /usage endpoint) copy the dict
# rather than holding the reference.
provider_totals: dict[str, float] = {}
provider_totals_hook: Optional[ProviderTotalsHook] = None


def initialize(settings: Settings) -> None:
    """Construct the guardrail singletons. Call once, before any router loads."""
    global cost_counter, ip_rate_limiter, state_backend, _enforce_ip_rate_limit_impl
    global provider_totals_hook

    state_backend = get_backend(
        kind=settings.state_backend_kind,
        data_dir=settings.data_dir,
        gcs_bucket=settings.gcs_state_bucket,
    )

    cost_counter = CostCounter(
        object_name="cost_counter.json",
        backend=state_backend,
        enabled=settings.guardrails_enabled,
        hourly_cap_usd=settings.cap_hourly_usd,
        daily_cap_usd=settings.cap_daily_usd,
        weekly_cap_usd=settings.cap_weekly_usd,
        per_token_cap_usd=settings.cap_per_token_usd,
    )
    cost_counter.load()

    ip_rate_limiter = IPRateLimiter()
    _enforce_ip_rate_limit_impl = make_enforce_ip_rate_limit(
        ip_rate_limiter,
        cap_rpm=settings.rate_limit_rpm,
        enabled=settings.guardrails_enabled,
    )

    provider_totals_hook = ProviderTotalsHook(provider_totals)


def enforce_ip_rate_limit(request: Request) -> None:
    """Stable wrapper — safe to pass to Depends() at import time.

    Reads through the lazily-set implementation so router imports don't
    capture ``None`` before ``initialize()`` has run.
    """
    if _enforce_ip_rate_limit_impl is None:
        raise RuntimeError(
            "app_state.enforce_ip_rate_limit invoked before initialize()"
        )
    _enforce_ip_rate_limit_impl(request)
