# Copyright (c) 2026 Eric Cooper.
"""Tests for the GCS index-sync guard logic.

We don't exercise a real bucket here — the value is proving the no-op
guards (local dev, missing bucket) and the best-effort failure contract,
so a misconfigured or flaky GCS never crash-loops the process.
"""

from __future__ import annotations

import rulebook.index_sync as index_sync


def _make_settings(monkeypatch, *, kind: str, bucket: str | None):
    monkeypatch.setattr(index_sync.settings, "state_backend_kind", kind)
    monkeypatch.setattr(index_sync.settings, "gcs_state_bucket", bucket)


def test_noop_when_local_backend(monkeypatch):
    _make_settings(monkeypatch, kind="local", bucket="whatever")
    assert index_sync.sync_index_from_gcs() is False


def test_noop_when_gcs_but_no_bucket(monkeypatch):
    _make_settings(monkeypatch, kind="gcs", bucket=None)
    assert index_sync.sync_index_from_gcs() is False


def test_gcs_failure_is_swallowed(monkeypatch, tmp_path):
    _make_settings(monkeypatch, kind="gcs", bucket="<SRC_BUCKET>")
    monkeypatch.setattr(index_sync.settings, "index_path", tmp_path / "index")

    # Force the lazy SDK import path to blow up; sync must not propagate.
    class _Boom:
        def Client(self, *a, **k):  # noqa: N802 — mirrors storage.Client
            raise RuntimeError("no credentials")

    import sys

    monkeypatch.setitem(sys.modules, "google.cloud", type(sys)("google.cloud"))
    monkeypatch.setattr(sys.modules["google.cloud"], "storage", _Boom(), raising=False)

    assert index_sync.sync_index_from_gcs() is False
