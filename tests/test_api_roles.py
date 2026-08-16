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
    # The casual tier: ask, rate, issue tags, plus a personal "Your activity"
    # page to revisit their own questions/ratings — nothing behind the curtain.
    assert body["capabilities"] == ["activity.view", "ask", "feedback.tag", "feedback.view", "rate"]


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

    # level8 has *.view.all → sees everyone's, with is_own flagging its own rows
    # (boss authored q2, gina authored q1) so the UI only offers Edit on own.
    _as(client, "tok_super")
    assert {g["qa_id"] for g in client.get("/advanced/golds").json()["golds"]} == {"q1", "q2"}
    fb = {f["qa_id"]: f for f in client.get("/advanced/feedback").json()["feedback"]}
    assert set(fb) == {"q1", "q2"}
    assert fb["q2"]["is_own"] is True and fb["q1"]["is_own"] is False


def test_questions_history_self_scoped(client, monkeypatch):
    import api.main as main

    qa = [
        {"qa_id": "q1", "question": "a?", "answer": "A", "sport": "ultimate", "timestamp": "t2", "author": "gina"},
        {"qa_id": "q2", "question": "b?", "answer": "B", "sport": None, "timestamp": "t1", "author": "boss"},
    ]
    feedback = [{"qa_id": "q1", "timestamp": "t", "rating": 4, "author": "gina"}]
    golds = [{"gold_id": "g1", "qa_id": "q1", "question": "a?", "gold_answer": "A", "timestamp": "t", "author": "gina"}]
    monkeypatch.setattr(main, "read_qa_entries", lambda: qa)
    monkeypatch.setattr(main, "read_latest_feedback", lambda: feedback)
    monkeypatch.setattr(main, "read_latest_golds", lambda: golds)

    # "My questions" is always self-scoped: gina sees only q1, with her rating
    # and gold joined in — never boss's q2.
    _as(client, "tok_l4")
    qs = client.get("/advanced/questions").json()["questions"]
    assert [q["qa_id"] for q in qs] == ["q1"]
    assert qs[0]["rating"] == 4 and qs[0]["has_gold"] is True and qs[0]["answer"] == "A"

    # activity.view is level1+, so a novice reaches it — and sees only their own
    # (none here → empty), never everyone's.
    _as(client, "tok_nov")
    assert client.get("/advanced/questions").json()["questions"] == []

    # level8 holds questions.view.all → sees everyone's, each stamped with its
    # asker, and is_own flags only the caller's own (boss authored q2).
    _as(client, "tok_super")
    qs = {q["qa_id"]: q for q in client.get("/advanced/questions").json()["questions"]}
    assert set(qs) == {"q1", "q2"}
    assert qs["q1"]["author"] == "gina" and qs["q1"]["is_own"] is False
    assert qs["q2"]["author"] == "boss" and qs["q2"]["is_own"] is True


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


def test_users_tab_reports_engagement(client, monkeypatch):
    # The Users list joins each token's weekly tokens + last_seen (from the
    # engagement counter) onto its allowlist row.
    import api.main as main
    import rulebook.app_state as app_state
    from rulebook.config import settings

    monkeypatch.setattr(settings, "state_backend_kind", "gcs")
    monkeypatch.setattr(settings, "gcs_state_bucket", "b")
    monkeypatch.setattr(main, "read_tokens_object", lambda *a: {"tok_zzz": "Zed", "tok_super": "boss"})
    # Activity counts key on the author label; join happens by label.
    monkeypatch.setattr(main, "count_questions_by_author", lambda: {"Zed": 7})
    monkeypatch.setattr(main, "count_comments_by_author", lambda: {"Zed": 3})
    monkeypatch.setattr(main, "count_golds_by_author", lambda: {"Zed": 2})

    # A unique token so other tests' /me touches can't perturb the count.
    app_state.token_counter.record(1200, token="tok_zzz")

    _as(client, "tok_super")
    rows = {r["label"]: r for r in client.get("/advanced/invite-tokens").json()["tokens"]}
    assert rows["Zed"]["weekly_tokens"] == 1200
    assert rows["Zed"]["last_seen"] is not None
    assert rows["Zed"]["questions"] == 7
    assert rows["Zed"]["comments"] == 3
    assert rows["Zed"]["golds"] == 2
    # boss recorded no activity → all zero.
    assert rows["boss"]["weekly_tokens"] == 0
    assert rows["boss"]["weekly_usd"] == 0.0
    assert rows["boss"]["questions"] == 0
    assert rows["boss"]["comments"] == 0
    assert rows["boss"]["golds"] == 0


def test_count_questions_by_author(monkeypatch):
    import rulebook.interaction_log as il

    fake = {
        "q1": {"author": "Ann"},
        "q2": {"author": "Ann"},
        "q3": {"author": "Bob"},
        "q4": {"author": None},  # anonymous / pre-adoption — skipped
    }
    monkeypatch.setattr(il, "read_latest", lambda *a, **k: fake)
    assert il.count_questions_by_author() == {"Ann": 2, "Bob": 1}


def test_count_golds_by_author(monkeypatch):
    import rulebook.interaction_log as il

    rows = [{"author": "Ann"}, {"author": "Ann"}, {"author": "Bob"}, {"author": None}]
    monkeypatch.setattr(il, "read_latest_golds", lambda: rows)
    assert il.count_golds_by_author() == {"Ann": 2, "Bob": 1}


def test_count_comments_by_author(tmp_path, monkeypatch):
    import json

    import rulebook.interaction_log as il

    fb = tmp_path / "feedback.jsonl"
    fb.write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                {"qa_id": "q1", "author": "Ann", "rating": 5, "comment": "great"},
                {"qa_id": "q1", "author": "Ann", "rating": 4, "comment": "edited"},  # same pair → 1
                {"qa_id": "q2", "author": "Ann", "rating": 3, "comment": "  "},       # blank → not a comment
                {"qa_id": "q3", "author": "Bob", "rating": 2, "comment": "meh"},
                {"qa_id": "q4", "author": "Bob", "rating": 1},                        # no comment field
                {"qa_id": "q5", "author": None, "rating": 5, "comment": "anon"},      # no author → skipped
            ]
        )
        + "\n"
    )
    monkeypatch.setattr(il, "_log_dir", lambda: tmp_path)
    assert il.count_comments_by_author() == {"Ann": 1, "Bob": 1}


def test_index_build_history(tmp_path, monkeypatch):
    import rulebook.interaction_log as il

    monkeypatch.setattr(il, "_log_dir", lambda: tmp_path)
    assert il.read_index_builds() == []  # none yet
    il.log_index_build({"build_id": "b1", "count": 100})
    il.log_index_build({"build_id": "b2", "count": 200})
    builds = il.read_index_builds()
    assert [b["build_id"] for b in builds] == ["b2", "b1"]  # newest first
    assert il.read_index_builds(limit=1)[0]["build_id"] == "b2"
