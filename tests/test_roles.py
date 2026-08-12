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


# ── Capabilities ────────────────────────────────────────────────────────────


def test_capability_bundles_preserve_ladder_policy():
    has = roles.has_capability
    # suspended: nothing.
    assert roles.capabilities_for("suspended") == frozenset()
    # novice: public tier only.
    assert has("novice", roles.CAP_ASK) and has("novice", roles.CAP_RATE)
    assert not has("novice", roles.CAP_ADVANCED_VIEW)
    # admin: full Advanced surface, but NOT user/role management (superuser-only).
    assert has("admin", roles.CAP_GOLDS_CURATE)
    assert has("admin", roles.CAP_INDEX_REBUILD)
    assert has("admin", roles.CAP_GOLDS_EDIT_ANY)
    assert not has("admin", roles.CAP_USERS_MANAGE)
    assert not has("admin", roles.CAP_ROLES_MANAGE)
    # superuser: everything meaningful. It carries golds.edit.any, so it does
    # NOT also carry the strictly-lesser golds.edit.own (the "your own only"
    # form) — that one is for restricted roles like curator.
    assert has("superuser", roles.CAP_USERS_MANAGE)
    assert has("superuser", roles.CAP_ROLES_MANAGE)
    assert has("superuser", roles.CAP_GOLDS_EDIT_ANY)
    assert not has("superuser", roles.CAP_GOLDS_EDIT_OWN)
    assert roles.capabilities_for("superuser") == roles.CAPABILITIES - {roles.CAP_GOLDS_EDIT_OWN}


def test_new_roles_capability_shape():
    has = roles.has_capability
    # observer: read the machinery, change nothing — and can still ask.
    assert has("observer", roles.CAP_ASK)
    assert has("observer", roles.CAP_ADVANCED_VIEW)
    assert has("observer", roles.CAP_GOLDS_VIEW)
    for cap in (roles.CAP_GOLDS_CURATE, roles.CAP_INDEX_REBUILD, roles.CAP_USERS_MANAGE):
        assert not has("observer", cap)
    # curator-lite: observer + toggle Incl. + rebuild.
    assert has("curator-lite", roles.CAP_GOLDS_CURATE)
    assert has("curator-lite", roles.CAP_INDEX_REBUILD)
    assert not has("curator-lite", roles.CAP_GOLD_AUTHOR)
    # curator: can author/edit OWN golds, never ANY (the own/any split).
    assert has("curator", roles.CAP_GOLD_AUTHOR)
    assert has("curator", roles.CAP_GOLDS_EDIT_OWN)
    assert not has("curator", roles.CAP_GOLDS_EDIT_ANY)
    assert not has("curator", roles.CAP_USERS_MANAGE)


def test_unknown_role_has_no_capabilities():
    assert roles.capabilities_for("wizard") == frozenset()
    assert not roles.has_capability("wizard", roles.CAP_ASK)


def test_require_capability_public_mode(monkeypatch):
    monkeypatch.setattr(roles.settings, "demo_mode", False)
    monkeypatch.setattr(roles, "get_current_guest", lambda: None)
    # Public tier stays open (anonymous /ask, /feedback rating)...
    roles.require_capability(roles.CAP_ASK)()
    roles.require_capability(roles.CAP_RATE)()
    # ...but anything on the Advanced surface fails closed with no auth.
    for cap in (roles.CAP_ADVANCED_VIEW, roles.CAP_GOLDS_CURATE, roles.CAP_USERS_MANAGE):
        with pytest.raises(HTTPException) as ei:
            roles.require_capability(cap)()
        assert ei.value.status_code == 403


def test_require_capability_enforced_in_demo(local_backend, monkeypatch):
    monkeypatch.setattr(roles.settings, "initial_roles", {"tok_ob": "observer"})
    monkeypatch.setattr(
        roles, "get_current_guest", lambda: GuestIdentity(token="tok_ob", recipient="ob")
    )
    roles.require_capability(roles.CAP_GOLDS_VIEW)()   # observer may view
    with pytest.raises(HTTPException) as ei:
        roles.require_capability(roles.CAP_GOLDS_CURATE)()  # but not curate
    assert ei.value.status_code == 403
