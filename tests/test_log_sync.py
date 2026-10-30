# Copyright (c) 2026 Eric Cooper.
"""Tests for the GCS log-sync guard logic.

Like test_index_sync, we don't hit a real bucket — the value is proving the
no-op guards (local dev, missing bucket) and the best-effort failure
contract, so a misconfigured or flaky GCS never breaks a request or boot.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import rulebook.interaction_log as interaction_log
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
    _make_settings(monkeypatch, kind="gcs", bucket="test-state-bucket", data_root=tmp_path)
    _boom_storage(monkeypatch)
    # A GCS failure at boot must not propagate.
    log_sync.sync_logs_from_gcs()


def test_persist_failure_is_swallowed(monkeypatch, tmp_path):
    _make_settings(monkeypatch, kind="gcs", bucket="test-state-bucket", data_root=tmp_path)
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


def _appended_filenames() -> set[str]:
    """Every filename that interaction_log passes to ``_append``.

    Parsed from the source so the check can't drift out of sync with a
    logger that happens not to be exercised elsewhere. Resolves both string
    literals (``_append("audit.jsonl", ...)``) and module-level string
    constants (``_append(INDEX_BUILDS_LOG, ...)``); anything it can't resolve
    fails loudly rather than being silently skipped.
    """
    tree = ast.parse(Path(interaction_log.__file__).read_text())
    consts: dict[str, str] = {
        target.id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    names: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_append"
            and node.args
        ):
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                names.add(arg.value)
            elif isinstance(arg, ast.Name) and arg.id in consts:
                names.add(consts[arg.id])
            else:
                raise AssertionError(
                    f"test_every_appended_log_is_synced can't resolve the "
                    f"filename in an _append() call: {ast.dump(arg)}"
                )
    return names


def test_every_appended_log_is_synced():
    """Regression guard for #241: ``audit.jsonl`` was written via ``_append``
    but missing from ``LOG_FILES``, so it was never pulled at boot — and after
    a cold start the shrink guard would eventually overwrite the remote with
    only post-boot rows, losing audit history. Every log the app appends to
    MUST be in ``LOG_FILES`` or it isn't durable on the GCS backend.
    """
    appended = _appended_filenames()
    assert appended, "parsed no _append() filenames — the AST walk is broken"
    missing = appended - set(log_sync.LOG_FILES)
    assert not missing, (
        f"these logs are appended but missing from log_sync.LOG_FILES, so they "
        f"are never synced to/from GCS and will be lost on restart: {sorted(missing)}"
    )
