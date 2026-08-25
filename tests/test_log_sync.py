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
    _make_settings(monkeypatch, kind="gcs", bucket="rulebook-state", data_root=tmp_path)
    _boom_storage(monkeypatch)
    # A GCS failure at boot must not propagate.
    log_sync.sync_logs_from_gcs()


def test_persist_failure_is_swallowed(monkeypatch, tmp_path):
    _make_settings(monkeypatch, kind="gcs", bucket="rulebook-state", data_root=tmp_path)
    logs = tmp_path / "logs"
    logs.mkdir(parents=True)
    (logs / "gold.jsonl").write_text('{"qa_id":"x"}\n')
    _boom_storage(monkeypatch)
    # An upload failure must not propagate to the request.
    log_sync.persist_log("gold.jsonl")


def _fake_storage(monkeypatch, *, remote_size, uploads):
    """Fake google.cloud.storage: get_blob() reports remote_size (None = absent);
    blob().upload_from_filename() records the path so we can assert it ran."""
    class _Blob:
        def __init__(self, size=None):
            self.size = size
        def upload_from_filename(self, p):
            uploads.append(p)
    class _Bucket:
        def get_blob(self, name):
            return _Blob(remote_size) if remote_size is not None else None
        def blob(self, name):
            return _Blob()
    class _Client:
        def bucket(self, name):
            return _Bucket()
    class _Storage:
        def Client(self, *a, **k):  # noqa: N802 — mirrors storage.Client
            return _Client()
    monkeypatch.setitem(sys.modules, "google.cloud", type(sys)("google.cloud"))
    monkeypatch.setattr(sys.modules["google.cloud"], "storage", _Storage(), raising=False)


def test_persist_refuses_to_shrink_remote(monkeypatch, tmp_path):
    # #165: a stale (smaller) local copy must NOT clobber a larger remote.
    _make_settings(monkeypatch, kind="gcs", bucket="b", data_root=tmp_path)
    logs = tmp_path / "logs"; logs.mkdir(parents=True)
    (logs / "gold.jsonl").write_text('{"gold_id":"g1"}\n')  # tiny local
    uploads: list = []
    _fake_storage(monkeypatch, remote_size=10_000, uploads=uploads)  # remote much bigger
    log_sync.persist_log("gold.jsonl")
    assert uploads == []  # refused — would have shrunk the durable log


def test_persist_uploads_when_growing_or_new(monkeypatch, tmp_path):
    _make_settings(monkeypatch, kind="gcs", bucket="b", data_root=tmp_path)
    logs = tmp_path / "logs"; logs.mkdir(parents=True)
    (logs / "gold.jsonl").write_text('{"gold_id":"g1"}\n' * 100)  # large local
    uploads: list = []
    # remote smaller than local → normal append-and-grow, uploads.
    _fake_storage(monkeypatch, remote_size=5, uploads=uploads)
    log_sync.persist_log("gold.jsonl")
    assert len(uploads) == 1
    # remote absent (first write) → uploads.
    uploads.clear()
    _fake_storage(monkeypatch, remote_size=None, uploads=uploads)
    log_sync.persist_log("gold.jsonl")
    assert len(uploads) == 1
