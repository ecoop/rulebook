"""embeddings._record_embed_usage fires the real guardrail hook chain.

Embeddings don't go through guarded_call; they post usage via record_usage
with the same hook chain (WindowedCapHook + provider_totals_hook +
EventLogHook). This checks that path reaches ProviderTotals — the wiring that
feeds the per-provider line in the Usage widget.
"""

from rulebook import app_state, embeddings
from rulebook.config import Settings


def test_record_embed_usage_reaches_provider_totals():
    app_state.initialize(Settings())
    before = app_state.provider_totals.snapshot().get("voyage", 0.0)

    embeddings._record_embed_usage("voyage", "voyage-4", 1000, "document")

    after = app_state.provider_totals.snapshot()
    # The hook chain fired and recorded under the provider key (cost is >0 if
    # voyage-4 is priced, else 0.0 — either way the key is now present and the
    # running total is non-decreasing).
    assert "voyage" in after
    assert after["voyage"] >= before


def test_record_embed_usage_noop_without_initialize(monkeypatch):
    # Guard path: if initialize() never ran, cost_counter is None and the
    # helper returns silently rather than dereferencing a None hook chain.
    monkeypatch.setattr(app_state, "cost_counter", None)
    embeddings._record_embed_usage("voyage", "voyage-4", 1000, "document")  # must not raise
