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
    assert roles.at_least("level7", "level1")
    assert roles.at_least("level1", "level1")
    assert not roles.at_least("level1", "level7")
    assert not roles.at_least("level0", "level1")
    # Unknown role never counts as elevated.
    assert not roles.at_least("wizard", "level1")


def test_level_number():
    assert roles.level_number("level0") == 0
    assert roles.level_number("level8") == 8
    assert roles.level_number("wizard") == 0   # unknown → floor
    # every level carries a color + description for the badge
    assert set(roles.ROLE_LEVELS["level5"]) == {"level", "color", "description"}


def test_overrides_from_rows_replay():
    rows = [
        {"token": "a", "role": "level1"},
        {"token": "a", "role": "level3"},   # latest wins
        {"token": "b", "role": "level7"},
        {"token": "b", "role": "reset"},     # cleared
        {"token": "c", "role": "bogus"},     # invalid ignored
    ]
    assert roles.overrides_from_rows(rows) == {"a": "level3"}


def test_resolve_prefers_override_then_seed_then_default(local_backend, monkeypatch):
    monkeypatch.setattr(roles.settings, "initial_roles", {"tok_seed": "level7"})
    assert roles.resolve_role("tok_seed") == "level7"       # seed
    assert roles.resolve_role("tok_unknown") == "level1"    # default
    assert roles.resolve_role(None) == "level1"


def test_public_mode_allows_default_denies_privileged(monkeypatch):
    monkeypatch.setattr(roles.settings, "demo_mode", False)
    monkeypatch.setattr(roles, "get_current_guest", lambda: None)
    # Public tier stays open so /ask works with no auth...
    roles.require_role("level1")()  # does not raise
    # ...but privileged tiers fail closed (no anonymous admin/role writes).
    for tier in ("level3", "level7", "level8"):
        with pytest.raises(HTTPException) as ei:
            roles.require_role(tier)()
        assert ei.value.status_code == 403


def test_require_role_enforced_in_demo(local_backend, monkeypatch):
    monkeypatch.setattr(roles.settings, "initial_roles", {"tok_ev": "level3"})
    monkeypatch.setattr(
        roles, "get_current_guest", lambda: GuestIdentity(token="tok_ev", recipient="ev")
    )
    roles.require_role("level1")()   # level3 ≥ level1
    roles.require_role("level3")()   # equal
    with pytest.raises(HTTPException) as ei:
        roles.require_role("level7")()   # level3 < level7
    assert ei.value.status_code == 403


def test_suspended_blocked_everywhere(local_backend, monkeypatch):
    monkeypatch.setattr(roles.settings, "initial_roles", {"tok_x": "level0"})
    monkeypatch.setattr(
        roles, "get_current_guest", lambda: GuestIdentity(token="tok_x", recipient="x")
    )
    with pytest.raises(HTTPException):
        roles.require_role("level1")()  # suspended (level0) fails the floor


# ── Capabilities ────────────────────────────────────────────────────────────


def test_rungs_are_monotonic():
    # Each level must be a strict superset of the one below it (§4).
    levels = [f"level{n}" for n in range(9)]
    for lower, higher in zip(levels, levels[1:]):  # noqa: B905 — offset pairs, unequal by design
        lo, hi = roles.capabilities_for(lower), roles.capabilities_for(higher)
        assert lo < hi, f"{higher} must strictly extend {lower}"
    # level8 (superuser) is the top and holds every capability.
    assert roles.capabilities_for("level8") == roles.CAPABILITIES


def test_rung_boundaries():
    has = roles.has_capability
    # level1: ask/rate/tag, but no comment and nothing behind the curtain.
    assert has("level1", roles.CAP_FEEDBACK_TAG)
    assert not has("level1", roles.CAP_FEEDBACK_COMMENT)
    assert not has("level1", roles.CAP_ADVANCED_VIEW)
    # level2 gains the comment; level3 gains gold authoring.
    assert has("level2", roles.CAP_FEEDBACK_COMMENT)
    assert not has("level2", roles.CAP_GOLD_AUTHOR)
    assert has("level3", roles.CAP_GOLD_AUTHOR)
    assert not has("level3", roles.CAP_ADVANCED_VIEW)
    # level4: behind the curtain, self, read-mostly — edits own, not curate.
    assert has("level4", roles.CAP_ADVANCED_VIEW)
    assert has("level4", roles.CAP_PASSAGES_VIEW)
    assert has("level4", roles.CAP_GOLDS_EDIT_OWN)
    for cap in (roles.CAP_GOLDS_VIEW_ALL, roles.CAP_GOLDS_CURATE, roles.CAP_ATTRIBUTION_VIEW):
        assert not has("level4", cap)
    # level5: self → all (read), still no curate/clone/attribution.
    assert has("level5", roles.CAP_GOLDS_VIEW_ALL)
    assert has("level5", roles.CAP_FEEDBACK_VIEW_ALL)
    assert not has("level5", roles.CAP_GOLDS_CURATE)
    assert not has("level5", roles.CAP_ATTRIBUTION_VIEW)
    # level6: curate/clone/rebuild + the attribution wall — but no Users.
    for cap in (roles.CAP_GOLDS_CURATE, roles.CAP_GOLDS_CLONE, roles.CAP_INDEX_REBUILD,
                roles.CAP_SOURCES_CURATE, roles.CAP_ATTRIBUTION_VIEW):
        assert has("level6", cap)
    assert not has("level6", roles.CAP_USERS_VIEW)
    # level7 (admin): Users tab, change role, add invitees — but not remove/rename.
    for cap in (roles.CAP_USERS_VIEW, roles.CAP_USERS_CHANGE_ROLE, roles.CAP_USERS_ADD):
        assert has("level7", cap)
    for cap in (roles.CAP_USERS_REMOVE, roles.CAP_USERS_RENAME, roles.CAP_ROLES_MANAGE):
        assert not has("level7", cap)
    # level8 (superuser): the destructive ops + the RBAC-config editor.
    for cap in (roles.CAP_USERS_REMOVE, roles.CAP_USERS_RENAME, roles.CAP_ROLES_MANAGE):
        assert has("level8", cap)
    # No role edits another's gold in place — clone replaced edit.any.
    assert not hasattr(roles, "CAP_GOLDS_EDIT_ANY")


def test_capability_fingerprint():
    fp = roles.capability_fingerprint
    # Order-independent: the same SET always yields the same 8-hex fingerprint.
    assert fp(["ask", "rate", "gold.author"]) == fp(["gold.author", "ask", "rate"])
    assert len(fp(["ask"])) == 8
    # Any change to the set changes the fingerprint.
    assert fp(["ask", "rate"]) != fp(["ask", "rate", "gold.author"])
    # level3 (Contributor) = {ask, rate, feedback.tag, feedback.comment, gold.author};
    # sorted+hashed → the value shown in docs/rbac-data-driven-roles.md.
    assert roles.role_fingerprint("level3") == "8cee04a2"
    # Distinct bundles → distinct fingerprints.
    assert roles.role_fingerprint("level3") != roles.role_fingerprint("level4")


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
    monkeypatch.setattr(roles.settings, "initial_roles", {"tok_g": "level4"})
    monkeypatch.setattr(
        roles, "get_current_guest", lambda: GuestIdentity(token="tok_g", recipient="g")
    )
    roles.require_capability(roles.CAP_GOLDS_VIEW)()   # level4 may view
    with pytest.raises(HTTPException) as ei:
        roles.require_capability(roles.CAP_GOLDS_CURATE)()  # but not curate
    assert ei.value.status_code == 403
