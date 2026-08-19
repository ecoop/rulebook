# Copyright (c) 2026 Eric Cooper.
"""Tests for per-user domain access (#112): replay, resolution, constrain."""

from __future__ import annotations

import pytest

import rulebook.allowed_domains as als


@pytest.fixture(autouse=True)
def _clear_cache():
    als._grants_cache.clear()
    yield
    als._grants_cache.clear()


@pytest.fixture
def local_backend(monkeypatch):
    # Local backend (no GCS) so resolution falls to seed/default; grants come
    # from initial_allowed_domains + the configured default.
    monkeypatch.setattr(als.settings, "state_backend_kind", "local")
    monkeypatch.setattr(als.settings, "gcs_state_bucket", None)
    monkeypatch.setattr(als.settings, "initial_allowed_domains", {})
    monkeypatch.setattr(als.settings, "default_allowed_domains", ["ultimate", "goaltimate"])


def test_grants_from_rows_replay():
    rows = [
        {"token": "a", "domains": ["ultimate"]},
        {"token": "a", "domains": ["ultimate", "badminton"]},  # latest wins
        {"token": "b", "domains": "*"},                          # grant-all
        {"token": "c", "domains": ["curling"]},
        {"token": "c", "domains": "reset"},                      # cleared
        {"token": "d", "domains": "bogus"},                      # malformed → skip
        {"token": "", "domains": ["ultimate"]},                  # no token → skip
    ]
    assert als.grants_from_rows(rows) == {
        "a": ["ultimate", "badminton"],
        "b": "*",
    }


def test_resolve_default_for_unknown_token(local_backend):
    # A token with no grant resolves to the CONCRETE default, not "all".
    assert als.resolve_allowed_domains("nobody") == ["ultimate", "goaltimate"]


def test_resolve_none_for_missing_identity(local_backend):
    # No identity (demo off / public deploy) = unrestricted.
    assert als.resolve_allowed_domains(None) is None


def test_resolve_seed_grant(local_backend, monkeypatch):
    monkeypatch.setattr(
        als.settings, "initial_allowed_domains", {"alice": ["ultimate", "badminton"]}
    )
    assert als.resolve_allowed_domains("alice") == ["ultimate", "badminton"]


def test_constrain_unrestricted_passes_through():
    # allowed=None → requested passes through; empty stays None (= global all).
    assert als.constrain_sports(["ultimate"], None) == ["ultimate"]
    assert als.constrain_sports(None, None) is None
    assert als.constrain_sports([], None) is None


def test_constrain_empty_selection_becomes_full_allowlist():
    # A scoped caller asking for "all" gets their concrete allowlist, never
    # the global all — the leak footgun stays unreached.
    assert als.constrain_sports(None, ["ultimate", "goaltimate"]) == ["ultimate", "goaltimate"]
    assert als.constrain_sports([], ["ultimate"]) == ["ultimate"]


def test_constrain_intersects_and_preserves_order():
    assert als.constrain_sports(
        ["badminton", "ultimate", "curling"], ["ultimate", "badminton"]
    ) == ["badminton", "ultimate"]


def test_constrain_no_overlap_raises():
    with pytest.raises(PermissionError):
        als.constrain_sports(["badminton"], ["ultimate", "goaltimate"])
