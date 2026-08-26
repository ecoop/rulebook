# Copyright (c) 2026 Eric Cooper.
"""The fail-closed configured-model price guard (rulebook-21 / lcg#10).

A model llm-cost-governor can't price bills $0, so it never moves the cost
windows and WindowedCapHook never trips for it. These assert the guard refuses
to boot on that class when guardrails are on, warns (doesn't crash) when
they're off, and stays quiet for the models we actually ship. They assert
*shape and reachability*, never a dollar figure — a reprice upstream must not
turn this red.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from rulebook.app_state import _assert_models_priceable


def _settings(*, claude, embedding, guardrails):
    # The guard only reads these three attributes.
    return SimpleNamespace(
        claude_model=claude, embedding_model=embedding, guardrails_enabled=guardrails,
    )


def test_shipped_models_pass():
    # The models rulebook actually pins, priced by the installed lcg.
    _assert_models_priceable(_settings(claude="claude-sonnet-5", embedding="voyage-4", guardrails=True))


# A clearly-fake id no lcg version prices — version-independent, unlike a dated
# alias whose key may or may not still exist in the installed release.
_UNPRICED = "claude-bogus-does-not-exist-000"


def test_unpriced_model_fails_closed_when_guardrails_on():
    # A typo'd / dropped / dated id lcg can't price → refuse to boot rather than
    # under-enforce the caps.
    s = _settings(claude=_UNPRICED, embedding="voyage-4", guardrails=True)
    with pytest.raises(RuntimeError, match="price at \\$0"):
        _assert_models_priceable(s)


def test_unpriced_model_only_warns_when_guardrails_off():
    # Local dev has no caps to under-enforce — warn, never crash.
    s = _settings(claude=_UNPRICED, embedding="voyage-4", guardrails=False)
    _assert_models_priceable(s)  # must not raise


# --- role guard (lcg 0.4.0 capability catalog) ----------------------------

from rulebook.app_state import _assert_model_roles  # noqa: E402


def test_shipped_models_have_correct_roles():
    _assert_model_roles(_settings(claude="claude-sonnet-5", embedding="voyage-4", guardrails=True))


def test_embedding_id_in_chat_slot_fails_closed():
    # voyage-4 is priced (>$0) so the price guard passes it — but it's the wrong
    # KIND for CLAUDE_MODEL. The role guard is what catches the swap.
    s = _settings(claude="voyage-4", embedding="voyage-4", guardrails=True)
    with pytest.raises(RuntimeError, match="not a chat model"):
        _assert_model_roles(s)


def test_chat_id_in_embedding_slot_fails_closed():
    s = _settings(claude="claude-sonnet-5", embedding="claude-sonnet-5", guardrails=True)
    with pytest.raises(RuntimeError, match="not an embedding model"):
        _assert_model_roles(s)


def test_role_mismatch_only_warns_when_guardrails_off():
    s = _settings(claude="voyage-4", embedding="voyage-4", guardrails=False)
    _assert_model_roles(s)  # must not raise
