# Copyright (c) 2026 Eric Cooper.
"""End-to-end gating: real InviteAuthMiddleware + require_role on the app.

Uses the local backend so `invite_tokens` = the seed and `/advanced/roles`
needs no GCS. Proves the dependencies are actually wired to the routes,
which the unit tests in test_roles.py can't see.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    from rulebook.config import settings

    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "state_backend_kind", "local")
    monkeypatch.setattr(settings, "gcs_state_bucket", None)
    monkeypatch.setattr(
        settings,
        "invite_tokens_seed",
        {"tok_super": "boss", "tok_admin": "chief", "tok_l4": "gina", "tok_nov": "newbie"},
    )
    monkeypatch.setattr(
        settings,
        "initial_roles",
        {"tok_super": "level8", "tok_admin": "level7", "tok_l4": "level4"},
    )

    import api.main as main

    return TestClient(main.app)


def _as(client: TestClient, token: str) -> None:
    client.cookies.set("guest_session", token)


def test_me_reports_seed_role(client):
    import rulebook.roles as roles

    _as(client, "tok_super")
    body = client.get("/me").json()
    assert body["recipient"] == "boss"
    assert body["role"] == "level8"
    assert body["level"] == 8
    assert body["demo_mode"] is True
    # /me carries the effective role's full capability bundle, sorted — this is
    # the contract the frontend renders tabs/columns/buttons against.
    assert body["capabilities"] == sorted(roles.ROLE_CAPABILITIES["level8"])
    assert "roles.manage" in body["capabilities"]
    # Fingerprint of the role's capability set — 8 hex, matches the helper.
    assert body["fingerprint"] == roles.role_fingerprint("level8")


def test_me_defaults_to_level1(client):
    _as(client, "tok_nov")
    body = client.get("/me").json()
    assert body["role"] == "level1"
    assert body["level"] == 1
    # The casual tier: ask, rate, and issue tags — nothing behind the curtain.
    assert body["capabilities"] == ["ask", "feedback.tag", "rate"]


def test_users_split_admin_vs_superuser(client):
    # #7 black (admin) manages users — view, change role, ADD invitees — so these
    # are authorized and fail only for lack of the gcs backend (400), not authz.
    _as(client, "tok_admin")
    assert client.get("/advanced/invite-tokens").status_code == 400
    assert client.post("/advanced/roles", json={"token": "tok_nov", "role": "level2"}).status_code == 400
    assert client.post("/advanced/invite-tokens", json={"label": "x"}).status_code == 400
    # ...but the destructive ops (remove / rename) stay superuser-only → 403.
    assert client.delete("/advanced/invite-tokens/tok_x").status_code == 403
    assert client.patch("/advanced/invite-tokens/tok_nov", json={"label": "y"}).status_code == 403


def test_admin_tabs_are_capability_gated(client):
    # /advanced/golds was admin-gated; a novice lacks golds.view → 403 (not a
    # rank comparison anymore, but the same outcome).
    _as(client, "tok_nov")
    assert client.get("/advanced/golds").status_code == 403


def test_admin_roles_superuser_only(client):
    _as(client, "tok_nov")
    assert client.get("/advanced/roles").status_code == 403

    _as(client, "tok_super")
    resp = client.get("/advanced/roles")
    assert resp.status_code == 200
    roles = {r["token"]: r for r in resp.json()["roles"]}
    assert roles["tok_super"]["role"] == "level8"
    assert roles["tok_super"]["source"] == "seed"


def test_post_role_needs_gcs(client):
    # superuser is authorized, but role writes require the gcs backend.
    _as(client, "tok_super")
    resp = client.post("/advanced/roles", json={"token": "tok_nov", "role": "level7"})
    assert resp.status_code == 400


def test_unauthenticated_is_gated(client):
    client.cookies.clear()
    # No valid cookie in demo_mode → middleware blocks before the route.
    assert client.get("/me", follow_redirects=False).status_code != 200


def test_golds_and_feedback_self_scoped(client, monkeypatch):
    import api.main as main

    golds = [
        {"gold_id": "g1", "qa_id": "q1", "question": "?", "gold_answer": "a", "timestamp": "t", "author": "gina"},
        {"gold_id": "g2", "qa_id": "q2", "question": "?", "gold_answer": "b", "timestamp": "t", "author": "boss"},
    ]
    feedback = [
        {"qa_id": "q1", "timestamp": "t", "rating": 5, "author": "gina"},
        {"qa_id": "q2", "timestamp": "t", "rating": 2, "author": "boss"},
    ]
    monkeypatch.setattr(main, "read_latest_golds", lambda: golds)
    monkeypatch.setattr(main, "read_latest_curation", lambda: {})
    monkeypatch.setattr(main, "read_latest_feedback", lambda: feedback)
    monkeypatch.setattr(main, "read_qa_questions", lambda: {})

    # level4 lacks *.view.all → sees only its own (author == "gina") rows.
    _as(client, "tok_l4")
    assert [g["qa_id"] for g in client.get("/advanced/golds").json()["golds"]] == ["q1"]
    assert [f["qa_id"] for f in client.get("/advanced/feedback").json()["feedback"]] == ["q1"]

    # level8 has *.view.all → sees everyone's.
    _as(client, "tok_super")
    assert {g["qa_id"] for g in client.get("/advanced/golds").json()["golds"]} == {"q1", "q2"}
    assert {f["qa_id"] for f in client.get("/advanced/feedback").json()["feedback"]} == {"q1", "q2"}


def test_clone_gold_creates_owned_copy(client, monkeypatch):
    import api.main as main

    src = {
        "gold_id": "gsrc", "qa_id": "q1", "question": "Q?",
        "gold_answer": "orig", "timestamp": "t", "author": "gina",
    }
    monkeypatch.setattr(main, "read_latest_golds", lambda: [src])
    monkeypatch.setattr(main, "log_audit", lambda **kw: None)
    calls: list = []
    monkeypatch.setattr(main, "log_gold", lambda qa_id, **kw: calls.append((qa_id, kw)))

    # level8 holds golds.clone → forks the gold into a new one owned by the caller.
    _as(client, "tok_super")
    resp = client.post("/advanced/golds/gsrc/clone")
    assert resp.status_code == 200
    new_id = resp.json()["gold_id"]
    assert new_id != "gsrc"
    qa_id, kw = calls[0]
    assert qa_id == "q1"
    assert kw["gold_id"] == new_id
    assert kw["gold_answer"] == "orig"    # content copied from the source
    assert kw["author"] == "boss"         # …but owned by the cloner (tok_super = "boss")

    # a role without golds.clone (level1 novice) is refused.
    _as(client, "tok_nov")
    assert client.post("/advanced/golds/gsrc/clone").status_code == 403


def test_mutation_is_audited_and_audit_is_gated(client, monkeypatch):
    import api.main as main

    audited: list = []
    monkeypatch.setattr(main, "log_audit", lambda **kw: audited.append(kw))
    monkeypatch.setattr(main, "log_gold_curation", lambda *a, **k: None)

    # A shared-state mutation records one audit row (actor / action / target).
    _as(client, "tok_super")
    assert client.post("/advanced/gold-curation", json={"gold_id": "g9", "included": False}).status_code == 200
    assert audited[-1]["action"] == "golds.curate"
    assert audited[-1]["target"] == "g9"
    assert audited[-1]["actor"] == "boss"
    # The row records the actor's capability-set fingerprint at the time.
    import rulebook.roles as roles

    assert audited[-1]["actor_fingerprint"] == roles.role_fingerprint("level8")

    # Reading the trail needs attribution.view (level 6+): level8 ok, level4 denied.
    monkeypatch.setattr(main, "read_audit", lambda limit=None: [])
    assert client.get("/advanced/audit").status_code == 200
    _as(client, "tok_l4")
    assert client.get("/advanced/audit").status_code == 403


def test_invite_tokens_superuser_only(client):
    _as(client, "tok_nov")
    assert client.get("/advanced/invite-tokens").status_code == 403
    assert client.post("/advanced/invite-tokens", json={"label": "x"}).status_code == 403
    assert client.patch("/advanced/invite-tokens/tok_x", json={"label": "y"}).status_code == 403
    assert client.delete("/advanced/invite-tokens/tok_x").status_code == 403


def test_invite_tokens_need_gcs(client):
    # superuser is authorized, but the local backend has no allowlist object.
    _as(client, "tok_super")
    assert client.get("/advanced/invite-tokens").status_code == 400
    assert client.post("/advanced/invite-tokens", json={"label": "x"}).status_code == 400
    assert client.patch("/advanced/invite-tokens/tok_x", json={"label": "y"}).status_code == 400
    assert client.delete("/advanced/invite-tokens/tok_x").status_code == 400
