# Copyright (c) 2026 Eric Cooper.
"""End-to-end gating: real InviteAuthMiddleware + require_role on the app.

Uses the local backend so `invite_tokens` = the seed and `/admin/roles`
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
        settings, "invite_tokens_seed", {"tok_super": "boss", "tok_nov": "newbie"}
    )
    monkeypatch.setattr(settings, "initial_roles", {"tok_super": "superuser"})

    import api.main as main

    return TestClient(main.app)


def _as(client: TestClient, token: str) -> None:
    client.cookies.set("guest_session", token)


def test_me_reports_seed_role(client):
    _as(client, "tok_super")
    body = client.get("/me").json()
    assert body == {"recipient": "boss", "role": "superuser", "demo_mode": True}


def test_me_defaults_to_novice(client):
    _as(client, "tok_nov")
    assert client.get("/me").json()["role"] == "novice"


def test_admin_roles_superuser_only(client):
    _as(client, "tok_nov")
    assert client.get("/admin/roles").status_code == 403

    _as(client, "tok_super")
    resp = client.get("/admin/roles")
    assert resp.status_code == 200
    roles = {r["token"]: r for r in resp.json()["roles"]}
    assert roles["tok_super"]["role"] == "superuser"
    assert roles["tok_super"]["source"] == "seed"


def test_post_role_needs_gcs(client):
    # superuser is authorized, but role writes require the gcs backend.
    _as(client, "tok_super")
    resp = client.post("/admin/roles", json={"token": "tok_nov", "role": "admin"})
    assert resp.status_code == 400


def test_unauthenticated_is_gated(client):
    client.cookies.clear()
    # No valid cookie in demo_mode → middleware blocks before the route.
    assert client.get("/me", follow_redirects=False).status_code != 200


def test_invite_tokens_superuser_only(client):
    _as(client, "tok_nov")
    assert client.get("/admin/invite-tokens").status_code == 403
    assert client.post("/admin/invite-tokens", json={"label": "x"}).status_code == 403
    assert client.patch("/admin/invite-tokens/tok_x", json={"label": "y"}).status_code == 403
    assert client.delete("/admin/invite-tokens/tok_x").status_code == 403


def test_invite_tokens_need_gcs(client):
    # superuser is authorized, but the local backend has no allowlist object.
    _as(client, "tok_super")
    assert client.get("/admin/invite-tokens").status_code == 400
    assert client.post("/admin/invite-tokens", json={"label": "x"}).status_code == 400
    assert client.patch("/admin/invite-tokens/tok_x", json={"label": "y"}).status_code == 400
    assert client.delete("/admin/invite-tokens/tok_x").status_code == 400
