# Copyright (c) 2026 Eric Cooper.
"""Tests for RBAC: override replay, resolution, capability gating."""

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


def test_role_order():
    assert roles.role_order("suspended") == 0
    assert roles.role_order("superuser") == 8
    assert roles.role_order("wizard") == 0   # unknown → floor
    # every level carries an order + name + color + description for the badge
    assert set(roles.ROLE_LEVELS["reviewer"]) == {"order", "name", "color", "description"}
    assert roles.ROLE_LEVELS["reviewer"]["name"] == "Reviewer"


def test_ordered_roles():
    assert roles.ordered_roles() == (
        "suspended", "beginner", "annotator", "contributor", "builder",
        "reviewer", "director", "admin", "superuser",
    )


def test_legacy_ids_alias_to_canonical():
    # Old assignments (level ids + pre-level names) still resolve after the rename.
    assert roles.canonical_role("level8") == "superuser"
    assert roles.canonical_role("level3") == "contributor"
    assert roles.canonical_role("evaluator") == "contributor"
    assert roles.canonical_role("novice") == "beginner"
    assert roles.canonical_role("superuser") == "superuser"   # already canonical
    assert roles.canonical_role("wizard") == "wizard"         # unknown passes through
    # validity / caps / order all honor the alias
    assert roles.is_valid_role("level7")
    assert roles.capabilities_for("level5") == roles.capabilities_for("reviewer")
    assert roles.role_order("level0") == 0
    # append-only rows carrying legacy ids replay to canonical ids
    rows = [{"token": "t", "role": "level8"}, {"token": "u", "role": "evaluator"}]
    assert roles.overrides_from_rows(rows) == {"t": "superuser", "u": "contributor"}


def test_resolve_canonicalizes_legacy_seed(local_backend, monkeypatch):
    monkeypatch.setattr(roles.settings, "initial_roles", {"tok_old": "level7"})
    assert roles.resolve_role("tok_old") == "admin"


def test_overrides_from_rows_replay():
    rows = [
        {"token": "a", "role": "beginner"},
        {"token": "a", "role": "contributor"},   # latest wins
        {"token": "b", "role": "admin"},
        {"token": "b", "role": "reset"},     # cleared
        {"token": "c", "role": "bogus"},     # invalid ignored
    ]
    assert roles.overrides_from_rows(rows) == {"a": "contributor"}


def test_resolve_prefers_override_then_seed_then_default(local_backend, monkeypatch):
    monkeypatch.setattr(roles.settings, "initial_roles", {"tok_seed": "admin"})
    assert roles.resolve_role("tok_seed") == "admin"       # seed
    assert roles.resolve_role("tok_unknown") == "beginner"    # default
    assert roles.resolve_role(None) == "beginner"


# ── Capabilities ────────────────────────────────────────────────────────────


def test_rungs_are_monotonic():
    # Each level must be a strict superset of the one below it (§4).
    levels = list(roles.ordered_roles())
    for lower, higher in zip(levels, levels[1:]):  # noqa: B905 — offset pairs, unequal by design
        lo, hi = roles.capabilities_for(lower), roles.capabilities_for(higher)
        assert lo < hi, f"{higher} must strictly extend {lower}"
    # superuser (superuser) is the top and holds every capability.
    assert roles.capabilities_for("superuser") == roles.CAPABILITIES


def test_rung_boundaries():
    has = roles.has_capability
    # beginner: ask/rate/tag + a personal "Your activity" page (revisit your own
    # questions/ratings), but no comment and nothing behind the curtain.
    assert has("beginner", roles.CAP_FEEDBACK_TAG)
    assert has("beginner", roles.CAP_ACTIVITY_VIEW)
    assert has("beginner", roles.CAP_FEEDBACK_VIEW)
    assert not has("beginner", roles.CAP_FEEDBACK_COMMENT)
    assert not has("beginner", roles.CAP_GOLDS_VIEW)
    assert not has("beginner", roles.CAP_ADVANCED_VIEW)
    # annotator gains the comment; contributor gains gold authoring + revisiting own golds.
    assert has("annotator", roles.CAP_FEEDBACK_COMMENT)
    assert not has("annotator", roles.CAP_GOLD_AUTHOR)
    assert has("contributor", roles.CAP_GOLD_AUTHOR)
    assert has("contributor", roles.CAP_GOLDS_VIEW)
    assert has("contributor", roles.CAP_GOLDS_EDIT_OWN)
    assert not has("contributor", roles.CAP_ADVANCED_VIEW)
    # builder: the retrieval machinery (passages/sources), self, read-mostly —
    # it no longer INTRODUCES the self views (those moved down), but inherits them.
    assert has("builder", roles.CAP_ADVANCED_VIEW)
    assert has("builder", roles.CAP_PASSAGES_VIEW)
    assert has("builder", roles.CAP_SOURCES_VIEW)
    assert has("builder", roles.CAP_GOLDS_EDIT_OWN)
    for cap in (roles.CAP_GOLDS_VIEW_ALL, roles.CAP_GOLDS_CURATE, roles.CAP_ATTRIBUTION_VIEW):
        assert not has("builder", cap)
    # reviewer: self → all (read) across questions/feedback/golds — with authorship;
    # still no curate/clone, and the Audit tab (attribution.view) stays at director.
    assert has("reviewer", roles.CAP_GOLDS_VIEW_ALL)
    assert has("reviewer", roles.CAP_FEEDBACK_VIEW_ALL)
    assert has("reviewer", roles.CAP_QUESTIONS_VIEW_ALL)
    assert not has("builder", roles.CAP_QUESTIONS_VIEW_ALL)
    assert not has("reviewer", roles.CAP_GOLDS_CURATE)
    assert not has("reviewer", roles.CAP_ATTRIBUTION_VIEW)
    # director: curate/clone/rebuild + the attribution wall — but no Users.
    for cap in (roles.CAP_GOLDS_CURATE, roles.CAP_GOLDS_CLONE, roles.CAP_INDEX_REBUILD,
                roles.CAP_SOURCES_CURATE, roles.CAP_ATTRIBUTION_VIEW):
        assert has("director", cap)
    assert not has("director", roles.CAP_USERS_VIEW)
    # admin (admin): Users tab, change role, add invitees — but not remove/rename.
    for cap in (roles.CAP_USERS_VIEW, roles.CAP_USERS_CHANGE_ROLE, roles.CAP_USERS_ADD):
        assert has("admin", cap)
    for cap in (roles.CAP_USERS_REMOVE, roles.CAP_USERS_RENAME, roles.CAP_ROLES_MANAGE):
        assert not has("admin", cap)
    # superuser (superuser): the destructive ops + the RBAC-config editor.
    for cap in (roles.CAP_USERS_REMOVE, roles.CAP_USERS_RENAME, roles.CAP_ROLES_MANAGE):
        assert has("superuser", cap)
    # No role edits another's gold in place — clone replaced edit.any.
    assert not hasattr(roles, "CAP_GOLDS_EDIT_ANY")


def test_capability_fingerprint():
    fp = roles.capability_fingerprint
    # Order-independent: the same SET always yields the same 8-hex fingerprint.
    assert fp(["ask", "rate", "gold.author"]) == fp(["gold.author", "ask", "rate"])
    assert len(fp(["ask"])) == 8
    # Any change to the set changes the fingerprint.
    assert fp(["ask", "rate"]) != fp(["ask", "rate", "gold.author"])
    # contributor (Contributor) = {ask, rate, feedback.tag, activity.view, feedback.view,
    # feedback.comment, gold.author, golds.view, golds.edit.own}; sorted+hashed.
    assert roles.role_fingerprint("contributor") == "f4c9d61a"
    # Distinct bundles → distinct fingerprints.
    assert roles.role_fingerprint("contributor") != roles.role_fingerprint("builder")


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
    monkeypatch.setattr(roles.settings, "initial_roles", {"tok_g": "builder"})
    monkeypatch.setattr(
        roles, "get_current_guest", lambda: GuestIdentity(token="tok_g", recipient="g")
    )
    roles.require_capability(roles.CAP_GOLDS_VIEW)()   # builder may view
    with pytest.raises(HTTPException) as ei:
        roles.require_capability(roles.CAP_GOLDS_CURATE)()  # but not curate
    assert ei.value.status_code == 403
