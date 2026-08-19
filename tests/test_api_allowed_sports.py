# Copyright (c) 2026 Eric Cooper.
"""End-to-end per-user ruleset access (#112): the allowlist is wired to routes.

Local backend, so `/meta` falls back to DEFAULT_SPORTS and the allowlist comes
from `initial_allowed_sports` + the configured default. Proves the filtering /
enforcement dependencies are actually on the endpoints — the unit tests in
test_allowed_sports.py can't see that.
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
        {"tok_admin": "chief", "tok_ult": "una", "tok_nov": "newbie"},
    )
    monkeypatch.setattr(settings, "initial_roles", {"tok_admin": "level7"})
    monkeypatch.setattr(settings, "default_allowed_sports", ["ultimate", "goaltimate"])
    monkeypatch.setattr(settings, "initial_allowed_sports", {"tok_ult": ["ultimate"]})

    import api.main as main

    return TestClient(main.app)


def _as(client: TestClient, token: str) -> None:
    client.cookies.set("guest_session", token)


def test_meta_and_me_filter_to_allowlist(client):
    # tok_ult is granted only ultimate; goaltimate is filtered out of both the
    # picker menu (/meta) and the self view (/me).
    _as(client, "tok_ult")
    assert client.get("/meta").json()["sports"] == ["ultimate"]
    assert client.get("/me").json()["allowed_sports"] == ["ultimate"]


def test_meta_uses_default_for_ungranted_user(client):
    # No explicit grant → the concrete default (both current sports), NOT all.
    # /meta order follows the index; compare as a set. A ruleset added later
    # (badminton, curling) is not in the default, so it stays absent here.
    _as(client, "tok_nov")
    assert set(client.get("/meta").json()["sports"]) == {"ultimate", "goaltimate"}
    assert client.get("/me").json()["allowed_sports"] == ["ultimate", "goaltimate"]


def test_ask_rejects_disallowed_single_sport(client):
    # Enforced at the boundary, before retrieval — so this 403s without an index.
    _as(client, "tok_ult")
    resp = client.post("/ask", json={"question": "q?", "sport": "badminton"})
    assert resp.status_code == 403


def test_allowlist_read_is_local_but_writes_need_gcs(client):
    # Reading grants works on the local backend (seed/default), like
    # /advanced/roles: a row per known user plus the unfiltered menu.
    _as(client, "tok_admin")
    body = client.get("/advanced/allowed-sports").json()
    assert set(body["all_sports"]) >= {"ultimate", "goaltimate"}
    # The add-invite form pre-checks this; it's the concrete configured default.
    assert body["default_sports"] == ["ultimate", "goaltimate"]
    granted = {g["token"]: g for g in body["grants"]}
    assert granted["tok_ult"]["sports"] == ["ultimate"]
    assert granted["tok_ult"]["source"] == "seed"
    assert granted["tok_nov"]["source"] == "default"
    # Writing needs the append-only log → gcs backend, so 400 here (not 403).
    assert (
        client.post(
            "/advanced/allowed-sports", json={"token": "tok_nov", "sports": ["ultimate"]}
        ).status_code
        == 400
    )


def test_allowlist_write_refused_without_capability(client):
    # A novice (no users.change_role) is refused on authz, before the gcs check.
    _as(client, "tok_nov")
    assert (
        client.post(
            "/advanced/allowed-sports", json={"token": "tok_nov", "sports": ["ultimate"]}
        ).status_code
        == 403
    )
