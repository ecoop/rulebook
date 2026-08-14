# Copyright (c) 2026 Eric Cooper.
"""Index publish mirrors sync and no-ops off the gcs backend."""

from __future__ import annotations

from rulebook.index_sync import publish_index_to_gcs


def test_publish_index_noop_without_gcs(monkeypatch):
    import rulebook.index_sync as idx

    monkeypatch.setattr(idx.settings, "state_backend_kind", "local")
    monkeypatch.setattr(idx.settings, "gcs_state_bucket", None)
    assert publish_index_to_gcs() is False
