"""app_state.initialize() wiring + the upstream ProviderTotals hook (from #5).

Guards the llm-cost-governor migration: every singleton constructs, and the
ProviderTotalsHook accumulates per-provider USD the way /usage's snapshot()
reads it back.
"""

import types

from llm_cost_governor.provider_totals import ProviderTotals, ProviderTotalsHook

from rulebook import app_state
from rulebook.config import Settings


def test_initialize_builds_all_singletons():
    app_state.initialize(Settings())
    assert app_state.cost_counter is not None
    assert app_state.ip_rate_limiter is not None
    assert app_state.state_backend is not None
    assert isinstance(app_state.provider_totals, ProviderTotals)
    assert isinstance(app_state.provider_totals_hook, ProviderTotalsHook)
    # The hook and the read-model must be the same object so /usage sees writes.
    assert app_state.provider_totals_hook.totals is app_state.provider_totals


def test_provider_totals_accumulate_per_provider():
    app_state.initialize(Settings())  # fresh, empty totals
    hook = app_state.provider_totals_hook
    hook.post(None, types.SimpleNamespace(provider="anthropic", cost_usd=0.02))
    hook.post(None, types.SimpleNamespace(provider="voyage", cost_usd=0.001))
    hook.post(None, types.SimpleNamespace(provider="anthropic", cost_usd=0.03))

    snap = app_state.provider_totals.snapshot()
    assert snap == {"anthropic": 0.05, "voyage": 0.001}
    # This is exactly what api/main.py's /usage endpoint returns:
    assert (app_state.provider_totals.snapshot() if app_state.provider_totals else {}) == snap


def test_enforce_ip_rate_limit_is_callable_after_initialize():
    app_state.initialize(Settings())
    # Constructed and wired — a bad init would leave the impl None and raise.
    assert app_state._enforce_ip_rate_limit_impl is not None
