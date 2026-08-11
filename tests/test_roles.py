# Copyright (c) 2026 Eric Cooper.
"""Tests for RBAC: ladder comparison, override replay, resolution, gating."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from guest_auth import GuestIdentity

import rulebook.roles as roles


@pytest.fixture(autouse=True)
def _clear_cache():
    roles._overrides_cache.clear()
    yield
    roles._overrides_cache.clear()


@pytest.fixture
def local_backend(monkeypatch):
    # Default state: local backend (no GCS), demo on so gating is exercised.
    monkeypatch.setattr(roles.settings, "state_backend_kind", "local")
    monkeypatch.setattr(roles.settings, "gcs_state_bucket", None)
    monkeypatch.setattr(roles.settings, "demo_mode", True)
    monkeypatch.setattr(roles.settings, "initial_roles", {})


def test_ladder_monotonic():
    assert roles.at_least("admin", "novice")
    assert roles.at_least("novice", "novice")
    assert not roles.at_least("novice", "admin")
    assert not roles.at_least("suspended", "novice")
    # Unknown role never counts as elevated.
    assert not roles.at_least("wizard", "novice")


def test_overrides_from_rows_replay():
    rows = [
        {"token": "a", "role": "novice"},
        {"token": "a", "role": "evaluator"},   # latest wins
        {"token": "b", "role": "admin"},
        {"token": "b", "role": "reset"},        # cleared
        {"token": "c", "role": "bogus"},        # invalid ignored
    ]
    assert roles.overrides_from_rows(rows) == {"a": "evaluator"}


def test_resolve_prefers_override_then_seed_then_default(local_backend, monkeypatch):
    monkeypatch.setattr(roles.settings, "initial_roles", {"tok_seed": "admin"})
    assert roles.resolve_role("tok_seed") == "admin"        # seed
    assert roles.resolve_role("tok_unknown") == "novice"    # default
    assert roles.resolve_role(None) == "novice"


def test_public_mode_allows_novice_denies_privileged(monkeypatch):
    monkeypatch.setattr(roles.settings, "demo_mode", False)
    monkeypatch.setattr(roles, "get_current_guest", lambda: None)
    # Public tier stays open so /ask works with no auth...
    roles.require_role("novice")()  # does not raise
    # ...but privileged tiers fail closed (no anonymous admin/role writes).
    for tier in ("evaluator", "admin", "superuser"):
        with pytest.raises(HTTPException) as ei:
            roles.require_role(tier)()
        assert ei.value.status_code == 403


def test_require_role_enforced_in_demo(local_backend, monkeypatch):
    monkeypatch.setattr(roles.settings, "initial_roles", {"tok_ev": "evaluator"})
    monkeypatch.setattr(
        roles, "get_current_guest", lambda: GuestIdentity(token="tok_ev", recipient="ev")
    )
    roles.require_role("novice")()      # evaluator ≥ novice
    roles.require_role("evaluator")()   # equal
    with pytest.raises(HTTPException) as ei:
        roles.require_role("admin")()   # evaluator < admin
    assert ei.value.status_code == 403


def test_suspended_blocked_everywhere(local_backend, monkeypatch):
    monkeypatch.setattr(roles.settings, "initial_roles", {"tok_x": "suspended"})
    monkeypatch.setattr(
        roles, "get_current_guest", lambda: GuestIdentity(token="tok_x", recipient="x")
    )
    with pytest.raises(HTTPException):
        roles.require_role("novice")()  # suspended fails the floor
