# Copyright (c) 2026 Eric Cooper.
"""Tests for the GCS log-sync guard logic.

Like test_index_sync, we don't hit a real bucket — the value is proving the
no-op guards (local dev, missing bucket) and the best-effort failure
contract, so a misconfigured or flaky GCS never breaks a request or boot.
"""

from __future__ import annotations

import sys

import rulebook.log_sync as log_sync


def _make_settings(monkeypatch, *, kind, bucket, data_root=None):
    monkeypatch.setattr(log_sync.settings, "state_backend_kind", kind)
    monkeypatch.setattr(log_sync.settings, "gcs_state_bucket", bucket)
    if data_root is not None:
        monkeypatch.setattr(log_sync.settings, "data_root", data_root)


def _boom_storage(monkeypatch):
    class _Boom:
        def Client(self, *a, **k):  # noqa: N802 — mirrors storage.Client
            raise RuntimeError("no credentials")

    monkeypatch.setitem(sys.modules, "google.cloud", type(sys)("google.cloud"))
    monkeypatch.setattr(sys.modules["google.cloud"], "storage", _Boom(), raising=False)


def test_noop_when_local_backend(monkeypatch):
    _make_settings(monkeypatch, kind="local", bucket="whatever")
    assert log_sync._enabled() is False
    # Must not raise or touch the SDK.
    log_sync.sync_logs_from_gcs()
    log_sync.persist_log("gold.jsonl")


def test_noop_when_gcs_but_no_bucket(monkeypatch):
    _make_settings(monkeypatch, kind="gcs", bucket=None)
    assert log_sync._enabled() is False
    log_sync.sync_logs_from_gcs()
    log_sync.persist_log("gold.jsonl")


def test_sync_failure_is_swallowed(monkeypatch, tmp_path):
    _make_settings(monkeypatch, kind="gcs", bucket="<SRC_BUCKET>", data_root=tmp_path)
    _boom_storage(monkeypatch)
    # A GCS failure at boot must not propagate.
    log_sync.sync_logs_from_gcs()


def test_persist_failure_is_swallowed(monkeypatch, tmp_path):
    _make_settings(monkeypatch, kind="gcs", bucket="<SRC_BUCKET>", data_root=tmp_path)
    logs = tmp_path / "logs"
    logs.mkdir(parents=True)
    (logs / "gold.jsonl").write_text('{"qa_id":"x"}\n')
    _boom_storage(monkeypatch)
    # An upload failure must not propagate to the request.
    log_sync.persist_log("gold.jsonl")
