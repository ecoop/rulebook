# Copyright (c) 2026 Eric Cooper.
"""ANTHROPIC_API_KEY is optional: the key-free paths import and run without it,
and only generation enforces it — lazily, with a clear message.

Guards the newcomer story: a fresh clone can build an index, retrieve, and run
eval with no key at all; `ask` / the web app fail late and legibly if the key is
missing, instead of a confusing crash at import time.
"""

from __future__ import annotations

import pytest

from rulebook import generate
from rulebook.config import Settings, settings


def test_settings_construct_without_anthropic_key(monkeypatch) -> None:
    # No env var and no .env file — the key-free path's import must not blow up.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.anthropic_api_key is None


def test_generate_answer_raises_clearly_without_key(monkeypatch) -> None:
    # Generation is the ONE place the key is required; the guard fires before any
    # client construction or network call, so [] chunks is fine.
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        generate.generate_answer("how do you win?", [])
