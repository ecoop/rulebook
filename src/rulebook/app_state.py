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

import logging
from typing import Callable, Optional

from fastapi import Request

from guest_auth import get_current_guest
from llm_cost_governor.counters import CapDimension, CostCounter, RollingWeekCounter
from llm_cost_governor.fastapi_ext import make_enforce_ip_rate_limit
from llm_cost_governor.provider_totals import ProviderTotals, ProviderTotalsHook
from llm_cost_governor.ratelimit import IPRateLimiter
from llm_cost_governor.state import StateBackend, get_backend

from .config import Settings

log = logging.getLogger(__name__)


def _assert_models_priceable(settings: Settings) -> None:
    """Fail-closed guard: a model llm-cost-governor can't price bills $0, so it
    contributes nothing to the rolling cost windows and ``WindowedCapHook``
    never trips for it — the caps silently under-enforce (lcg#10). Refuse to
    boot when guardrails are on and any configured model prices at zero.

    Off (warn only) when guardrails are disabled — local dev has no caps to
    under-enforce. Resilient to an lcg pricing-API move: if the pricing symbol
    is gone we log and skip rather than crash boot for a non-config reason.
    """
    try:
        from llm_cost_governor.pricing import _cost
    except Exception:  # noqa: BLE001 — pricing API moved; don't crash boot over it
        log.warning(
            "cost governance: llm-cost-governor pricing API unavailable; "
            "skipping the configured-model price guard"
        )
        return

    configured = {
        "claude_model": settings.claude_model,
        "embedding_model": settings.embedding_model,
    }
    unpriced = []
    for field, model in configured.items():
        try:
            price = _cost(model, 1_000_000, 0)
        except Exception:  # noqa: BLE001 — an unknown/unpriceable model id
            price = 0.0
        if price <= 0:
            unpriced.append(f"{field}={model!r}")

    if not unpriced:
        return
    msg = (
        "cost governance: configured model(s) price at $0 in "
        f"llm-cost-governor — {', '.join(unpriced)}. Their spend would be "
        "invisible and the cost caps would under-enforce. Use a bare model "
        "alias lcg prices (no dated suffix)."
    )
    if settings.guardrails_enabled:
        raise RuntimeError(msg)
    log.warning(msg)


# Module-level singletons, populated by initialize().
cost_counter: Optional[CostCounter] = None
# Per-token engagement tally: weekly token count + last_seen, keyed by invite
# token. Not a guardrail (no cap enforced) — reuses the rolling-week counter
# purely to power the Users tab's "last seen" and "this week" columns.
token_counter: Optional[RollingWeekCounter] = None
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
    global cost_counter, token_counter, ip_rate_limiter, state_backend, _enforce_ip_rate_limit_impl
    global provider_totals, provider_totals_hook

    # Fail fast if a configured model can't be priced — an unpriced model makes
    # the cost caps silently under-enforce (see the guard's docstring).
    _assert_models_priceable(settings)

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

    # Engagement tally — one "token" dimension, no real cap (analytics, not a
    # guardrail): record() adds token counts on /ask and touches last_seen on
    # /me; we never call enforce(). Persists on the same backend as the caps.
    token_counter = RollingWeekCounter(
        name="token_usage",
        object_name="token_usage.json",
        backend=state_backend,
        dimensions=[CapDimension(name="token", cap=float("inf"), cap_id="token_week")],
        enabled=settings.guardrails_enabled,
    )
    token_counter.load()

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
