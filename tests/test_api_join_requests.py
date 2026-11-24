# Copyright (c) 2026 Eric Cooper.
"""Join requests through the real app (#337): gating, approve, decline, purge, settings.

The GCS pieces are swapped for in-memory fakes: the join store, the invite
allowlist object, and the role / domain-grant logs. The middleware and the
capability checks are real.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from rulebook import join_requests as jr


class Fakes:
    def __init__(self) -> None:
        self.store = jr.MemoryJoinStore()
        self.tokens: dict[str, str] = {"tok_existing": "Taken Name"}
        self.domain_rows: list[dict] = []
        self.role_rows: list[dict] = []
        self.audit: list[dict] = []

    def add(self, **kw) -> dict:
        fields = {"name": "Pat Lee", "email": "pat@example.org", "heard_about": "Tuesday pickup"}
        fields.update(kw)
        status = fields.pop("status", None)
        r = jr.new_request(**fields)
        if status:
            r["status"] = status
        self.store.put(r, version=0)
        return r


@pytest.fixture
def fakes(monkeypatch):
    from rulebook.config import settings

    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "state_backend_kind", "local")
    monkeypatch.setattr(settings, "gcs_state_bucket", None)
    monkeypatch.setattr(
        settings,
        "invite_tokens_seed",
        {"tok_super": "boss", "tok_admin": "chief", "tok_dir": "dee", "tok_nov": "newbie"},
    )
    monkeypatch.setattr(
        settings,
        "initial_roles",
        {"tok_super": "superuser", "tok_admin": "admin", "tok_dir": "director"},
    )
    monkeypatch.setattr(settings, "smtp_user", None)
    monkeypatch.setattr(settings, "smtp_password", None)

    import api.main as main

    f = Fakes()
    monkeypatch.setattr(main, "_join_store", lambda: f.store)
    monkeypatch.setattr(main, "_require_gcs_for_invite_tokens", lambda: ("bucket", "invite_tokens.json"))
    monkeypatch.setattr(main, "read_tokens_object", lambda b, o: dict(f.tokens))
    monkeypatch.setattr(main, "write_tokens_object", lambda b, o, m: (f.tokens.clear(), f.tokens.update(m)))
    monkeypatch.setattr(main, "append_allowed_domains_row", lambda b, o, row: f.domain_rows.append(row))
    monkeypatch.setattr(main, "append_role_row", lambda b, o, row: f.role_rows.append(row))
    monkeypatch.setattr(main, "available_domains", lambda: ["goaltimate", "ultimate"])
    monkeypatch.setattr(main, "log_audit", lambda **kw: f.audit.append(kw))
    f.client = TestClient(main.app)
    return f


def _as(f: Fakes, token: str) -> TestClient:
    f.client.cookies.set("guest_session", token)
    return f.client


# ── gating ──────────────────────────────────────────────────────────────────


def test_director_and_beginner_cannot_see_requests(fakes):
    for tok in ("tok_dir", "tok_nov"):
        c = _as(fakes, tok)
        assert c.get("/advanced/join-requests").status_code == 403
        assert c.get("/advanced/join-settings").status_code == 403


def test_admin_decides_but_only_superuser_purges(fakes):
    r = fakes.add()
    c = _as(fakes, "tok_admin")
    assert c.get("/advanced/join-requests").status_code == 200
    assert c.post("/advanced/join-requests/purge").status_code == 403
    assert c.post(f"/advanced/join-requests/{r['id']}/decline").status_code == 200
    c = _as(fakes, "tok_super")
    assert c.post("/advanced/join-requests/purge").json() == {"purged": 1}


def test_unauthenticated_is_gated(fakes):
    fakes.client.cookies.clear()
    assert fakes.client.get("/advanced/join-requests").status_code == 401


# ── list ────────────────────────────────────────────────────────────────────


def test_list_returns_requests_count_and_default_settings(fakes):
    fakes.add(name="A", now="2026-01-01T00:00:00Z")
    fakes.add(name="B", status="declined")
    body = _as(fakes, "tok_admin").get("/advanced/join-requests").json()
    assert [r["name"] for r in body["requests"]] == ["A", "B"]
    assert body["pending"] == 1
    s = body["settings"]
    assert s["mode"] == "closed" and s["accepting_public"] is False
    assert s["default_role"] == "beginner" and s["default_domains"] == ["goaltimate"]
    assert s["email_configured"] is False
    assert s["modes"] == ["closed", "referral-only", "open"]


# ── approve ─────────────────────────────────────────────────────────────────


def test_approve_with_defaults_creates_the_user(fakes):
    r = fakes.add()
    resp = _as(fakes, "tok_admin").post(f"/advanced/join-requests/{r['id']}/approve", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    token = body["token"]
    assert body["label"] == "Pat Lee"
    assert fakes.tokens[token] == "Pat Lee"
    assert fakes.domain_rows[-1]["token"] == token and fakes.domain_rows[-1]["domains"] == ["goaltimate"]
    assert fakes.role_rows[-1]["token"] == token and fakes.role_rows[-1]["role"] == "beginner"
    stored, _ = fakes.store.get(r["id"])
    assert stored["status"] == "approved"
    assert stored["decided_by"] == "chief"
    assert stored["invite_token"] == token
    assert stored["granted_role"] == "beginner" and stored["granted_domains"] == ["goaltimate"]
    assert fakes.audit[-1]["action"] == "requests.decide"
    assert fakes.audit[-1]["detail"]["decision"] == "approved"


def test_approve_uses_edited_settings_and_per_request_overrides(fakes):
    c = _as(fakes, "tok_admin")
    put = c.put(
        "/advanced/join-settings",
        json={"mode": "open", "pending_cap": 3, "default_role": "annotator", "default_domains": ["ultimate"]},
    )
    assert put.status_code == 200, put.text
    r1, r2 = fakes.add(name="One"), fakes.add(name="Two")
    c.post(f"/advanced/join-requests/{r1['id']}/approve", json={})
    assert fakes.role_rows[-1]["role"] == "annotator"
    assert fakes.domain_rows[-1]["domains"] == ["ultimate"]
    c.post(
        f"/advanced/join-requests/{r2['id']}/approve",
        json={"label": "Two T.", "role": "contributor", "domains": ["goaltimate", "ultimate"]},
    )
    assert fakes.role_rows[-1]["role"] == "contributor"
    assert fakes.domain_rows[-1]["domains"] == ["goaltimate", "ultimate"]
    assert "Two T." in fakes.tokens.values()


@pytest.mark.parametrize(
    "payload,status",
    [
        ({"role": "suspended"}, 422),
        ({"role": "emperor"}, 422),
        ({"domains": ["chess"]}, 422),
        ({"label": "Taken Name"}, 409),
        ({"label": "   "}, 422),
    ],
)
def test_approve_rejects_bad_input_and_leaves_request_pending(fakes, payload, status):
    r = fakes.add()
    resp = _as(fakes, "tok_admin").post(f"/advanced/join-requests/{r['id']}/approve", json=payload)
    assert resp.status_code == status, resp.text
    assert fakes.store.get(r["id"])[0]["status"] == "pending"
    assert list(fakes.tokens) == ["tok_existing"]


def test_approve_twice_or_after_decline_is_409(fakes):
    r = fakes.add()
    c = _as(fakes, "tok_admin")
    assert c.post(f"/advanced/join-requests/{r['id']}/approve", json={}).status_code == 200
    assert c.post(f"/advanced/join-requests/{r['id']}/approve", json={}).status_code == 409
    assert c.post(f"/advanced/join-requests/{r['id']}/decline").status_code == 409
    assert len(fakes.tokens) == 2  # tok_existing + the one approval


def test_approve_unknown_is_404(fakes):
    assert _as(fakes, "tok_admin").post("/advanced/join-requests/jr_nope/approve", json={}).status_code == 404


def test_failed_user_creation_reverts_request_to_pending(fakes, monkeypatch):
    import api.main as main

    def boom(*a, **k):
        raise RuntimeError("bucket down")

    monkeypatch.setattr(main, "write_tokens_object", boom)
    r = fakes.add()
    client = TestClient(main.app, raise_server_exceptions=False)
    client.cookies.set("guest_session", "tok_admin")
    assert client.post(f"/advanced/join-requests/{r['id']}/approve", json={}).status_code == 500
    stored, _ = fakes.store.get(r["id"])
    assert stored["status"] == "pending" and stored["invite_token"] is None


# ── decline + purge ─────────────────────────────────────────────────────────


def test_decline_keeps_the_record(fakes):
    r = fakes.add()
    resp = _as(fakes, "tok_admin").post(f"/advanced/join-requests/{r['id']}/decline")
    assert resp.status_code == 200
    assert resp.json()["status"] == "declined"
    stored, _ = fakes.store.get(r["id"])
    assert stored["status"] == "declined" and stored["email"] == "pat@example.org"
    assert fakes.tokens == {"tok_existing": "Taken Name"}


def test_purge_removes_declined_only_and_audits_a_count(fakes):
    p = fakes.add()
    a = fakes.add(status="approved")
    fakes.add(status="declined")
    fakes.add(status="declined")
    resp = _as(fakes, "tok_super").post("/advanced/join-requests/purge")
    assert resp.json() == {"purged": 2}
    assert {r["id"] for r, _ in fakes.store.list()} == {p["id"], a["id"]}
    assert fakes.audit[-1]["action"] == "requests.purge"
    assert fakes.audit[-1]["detail"] == {"purged": 2}  # a count, no names or emails


# ── settings ────────────────────────────────────────────────────────────────


def test_settings_put_is_validated(fakes):
    c = _as(fakes, "tok_admin")
    good = {"mode": "open", "pending_cap": 2, "default_role": "beginner", "default_domains": ["goaltimate"]}
    for bad in (
        {"mode": "ajar"},
        {"pending_cap": 0},
        {"default_role": "suspended"},
        {"default_domains": []},
        {"default_domains": ["chess"]},
    ):
        assert c.put("/advanced/join-settings", json={**good, **bad}).status_code == 422, bad
    assert fakes.store.read_settings() is None  # nothing written


def test_settings_put_persists_and_reports_accepting(fakes):
    c = _as(fakes, "tok_admin")
    body = c.put(
        "/advanced/join-settings",
        json={"mode": "open", "pending_cap": 1, "default_role": "beginner", "default_domains": ["goaltimate"]},
    ).json()
    assert body["accepting_public"] is True and body["updated_by"] == "chief"
    fakes.add()
    assert c.get("/advanced/join-settings").json()["accepting_public"] is False  # cap reached
    assert fakes.audit[-1]["action"] == "requests.configure"


def test_director_cannot_change_settings(fakes):
    c = _as(fakes, "tok_dir")
    body = {"mode": "open", "pending_cap": 2, "default_role": "beginner", "default_domains": ["goaltimate"]}
    assert c.put("/advanced/join-settings", json=body).status_code == 403


def test_test_email_needs_configuration(fakes):
    assert _as(fakes, "tok_admin").post("/advanced/join-settings/test-email").status_code == 400


def test_test_email_sends_to_notify_address(fakes, monkeypatch):
    import api.main as main
    from rulebook.config import settings

    monkeypatch.setattr(settings, "smtp_user", "sender@example.org")
    monkeypatch.setattr(settings, "smtp_password", "app-password")
    monkeypatch.setattr(settings, "notify_email", "ops@example.org")
    sent: list = []
    monkeypatch.setattr(main, "send_email", lambda **kw: sent.append(kw))
    resp = _as(fakes, "tok_admin").post("/advanced/join-settings/test-email")
    assert resp.json() == {"ok": True, "to": "ops@example.org"}
    assert sent[0]["to"] == "ops@example.org"


# ── add-user still works after the shared-helper refactor ──────────────────


def test_add_user_unchanged(fakes):
    resp = _as(fakes, "tok_admin").post("/advanced/invite-tokens", json={"label": "Sam"})
    assert resp.status_code == 200, resp.text
    token = resp.json()["token"]
    assert fakes.tokens[token] == "Sam"
    assert fakes.domain_rows[-1]["note"] == "assigned at user creation"
    assert fakes.role_rows == []  # add-user writes no role row (default beginner)
    assert _as(fakes, "tok_admin").post(
        "/advanced/invite-tokens", json={"label": "Dup", "token": "tok_existing"}
    ).status_code == 409
