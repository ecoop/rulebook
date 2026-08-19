# Copyright (c) 2026 Eric Cooper.
"""End-to-end: the registry is wired into /meta (enabled filter + labels, #113)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    from rulebook.config import settings

    # demo_mode off → no per-user allowlist filter, so /meta reflects the
    # registry alone (index ∩ enabled). Local backend → seed-only registry.
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "state_backend_kind", "local")
    monkeypatch.setattr(settings, "gcs_state_bucket", None)
    monkeypatch.setattr(
        settings,
        "initial_domains",
        {
            "ultimate": {"display_name": "Ultimate (USAU)"},
            "goaltimate": {"enabled": False},
        },
    )

    import rulebook.registry as registry

    registry._registry_cache.clear()

    import api.main as main

    return TestClient(main.app)


def test_meta_filters_disabled_and_returns_labels(client):
    body = client.get("/meta").json()
    # goaltimate is disabled in the registry → absent from the picker menu.
    assert "goaltimate" not in body["domains"]
    assert "ultimate" in body["domains"]
    # …and the display label rides along for the visible ones.
    assert body["domain_labels"]["ultimate"] == "Ultimate (USAU)"
