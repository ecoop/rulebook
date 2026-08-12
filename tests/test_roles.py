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


def test_rungs_are_monotonic():
    # Each rung must be a strict superset of the one below it (§4).
    chain = ["suspended", "novice", "commenter", "evaluator", "observer",
             "reviewer", "operator", "admin", "superuser"]
    for lower, higher in zip(chain, chain[1:]):  # noqa: B905 — offset pairs, unequal by design
        lo, hi = roles.capabilities_for(lower), roles.capabilities_for(higher)
        assert lo < hi, f"{higher} must strictly extend {lower}"
    # superuser is the top and holds every capability.
    assert roles.capabilities_for("superuser") == roles.CAPABILITIES


def test_rung_boundaries():
    has = roles.has_capability
    # #1 casual: ask/rate/tag, but no comment and nothing behind the curtain.
    assert has("novice", roles.CAP_FEEDBACK_TAG)
    assert not has("novice", roles.CAP_FEEDBACK_COMMENT)
    assert not has("novice", roles.CAP_ADVANCED_VIEW)
    # #2 gains the comment; #3 (evaluator) gains gold authoring.
    assert has("commenter", roles.CAP_FEEDBACK_COMMENT)
    assert not has("commenter", roles.CAP_GOLD_AUTHOR)
    assert has("evaluator", roles.CAP_GOLD_AUTHOR)
    assert not has("evaluator", roles.CAP_ADVANCED_VIEW)
    # #4 observer: behind the curtain, self, read-mostly — edits own, not curate.
    assert has("observer", roles.CAP_ADVANCED_VIEW)
    assert has("observer", roles.CAP_PASSAGES_VIEW)
    assert has("observer", roles.CAP_GOLDS_EDIT_OWN)
    for cap in (roles.CAP_GOLDS_VIEW_ALL, roles.CAP_GOLDS_CURATE, roles.CAP_ATTRIBUTION_VIEW):
        assert not has("observer", cap)
    # #5 reviewer: self → all (read), still no curate/clone/attribution.
    assert has("reviewer", roles.CAP_GOLDS_VIEW_ALL)
    assert has("reviewer", roles.CAP_FEEDBACK_VIEW_ALL)
    assert not has("reviewer", roles.CAP_GOLDS_CURATE)
    assert not has("reviewer", roles.CAP_ATTRIBUTION_VIEW)
    # #6 operator: curate/clone/rebuild + the attribution wall — but no Users.
    for cap in (roles.CAP_GOLDS_CURATE, roles.CAP_GOLDS_CLONE, roles.CAP_INDEX_REBUILD,
                roles.CAP_SOURCES_CURATE, roles.CAP_ATTRIBUTION_VIEW):
        assert has("operator", cap)
    assert not has("operator", roles.CAP_USERS_VIEW)
    # #7 admin: Users tab + change role, but roster mutations stay superuser.
    assert has("admin", roles.CAP_USERS_VIEW)
    assert has("admin", roles.CAP_USERS_CHANGE_ROLE)
    for cap in (roles.CAP_USERS_ADD, roles.CAP_USERS_REMOVE, roles.CAP_USERS_RENAME,
                roles.CAP_ROLES_MANAGE):
        assert not has("admin", cap)
    # #8 superuser: the roster mutations + the RBAC-config editor.
    for cap in (roles.CAP_USERS_ADD, roles.CAP_USERS_REMOVE, roles.CAP_USERS_RENAME,
                roles.CAP_ROLES_MANAGE):
        assert has("superuser", cap)
    # No role edits another's gold in place — clone replaced edit.any.
    assert not hasattr(roles, "CAP_GOLDS_EDIT_ANY")


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
    for cap in (roles.CAP_ADVANCED_VIEW, roles.CAP_GOLDS_CURATE, roles.CAP_USERS_VIEW):
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
