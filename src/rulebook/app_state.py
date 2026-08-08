"""Singleton facade for llm-cost-governor — see docs/integration.md in that repo.

Every consumer that needs the cost counter or the rate-limit dependency
imports from THIS module (``from rulebook import app_state``), never
from ``llm_cost_governor.*`` directly. Constructed once at server start
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

from typing import Callable, Optional

from fastapi import Request

from guest_auth import get_current_guest
from llm_cost_governor.counters import CostCounter
from llm_cost_governor.fastapi_ext import make_enforce_ip_rate_limit
from llm_cost_governor.provider_totals import ProviderTotals, ProviderTotalsHook
from llm_cost_governor.ratelimit import IPRateLimiter
from llm_cost_governor.state import StateBackend, get_backend

from .config import Settings

# Module-level singletons, populated by initialize().
cost_counter: Optional[CostCounter] = None
ip_rate_limiter: Optional[IPRateLimiter] = None
state_backend: Optional[StateBackend] = None
_enforce_ip_rate_limit_impl: Optional[Callable[[Request], None]] = None

# Per-provider running USD totals — the upstream ProviderTotals read-model,
# accumulated by ProviderTotalsHook on every LLM call. In-memory / since-boot
# (no backend, so it resets on restart). Readers (e.g. the /usage endpoint)
# call .snapshot() for a copy rather than holding the reference.
provider_totals: Optional[ProviderTotals] = None
provider_totals_hook: Optional[ProviderTotalsHook] = None


def current_guest_token() -> str | None:
    """Return the invite token of the current request's guest, or None.

    Passed as ``identity_provider`` to WindowedCapHook so per-guest cost
    caps (``cap_per_token_usd``) attribute spend to the specific invite.
    Returns None outside a request context or when demo_mode is off,
    which is the "no per-guest attribution" fallback the counter already
    handles cleanly.
    """
    guest = get_current_guest()
    return guest.token if guest is not None else None


def initialize(settings: Settings) -> None:
    """Construct the guardrail singletons. Call once, before any router loads."""
    global cost_counter, ip_rate_limiter, state_backend, _enforce_ip_rate_limit_impl
    global provider_totals, provider_totals_hook

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

    provider_totals = ProviderTotals()  # in-memory, since-boot per-provider USD
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
