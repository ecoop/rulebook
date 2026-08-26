# Copyright (c) 2026 Eric Cooper.
"""Tests for the GCS rules-sync (#170).

Like the index/log sync tests, we don't hit a real bucket — the value is
proving the off-GCS no-op, the best-effort failure contract (a bad pull never
breaks boot/rebuild), and that a good pull writes files under rules_dir.
"""

from __future__ import annotations

import sys
from pathlib import Path

import rulebook.rules_sync as rules_sync


def _make_gcs(monkeypatch, *, kind="gcs", bucket="b", data_root=None):
    monkeypatch.setattr(rules_sync.settings, "state_backend_kind", kind)
    monkeypatch.setattr(rules_sync.settings, "gcs_state_bucket", bucket)
    if data_root is not None:
        monkeypatch.setattr(rules_sync.settings, "data_root", data_root)


def _boom_storage(monkeypatch):
    class _Boom:
        def Client(self, *a, **k):  # noqa: N802 — mirrors storage.Client
            raise RuntimeError("no credentials")

    monkeypatch.setitem(sys.modules, "google.cloud", type(sys)("google.cloud"))
    monkeypatch.setattr(sys.modules["google.cloud"], "storage", _Boom(), raising=False)


def _fake_storage(monkeypatch, files: dict[str, bytes]):
    """google.cloud.storage stand-in: list_blobs yields a blob per `files` entry
    (keyed by full object name), and download_to_filename writes its bytes."""
    class _Blob:
        def __init__(self, name, data):
            self.name = name
            self._data = data

        def download_to_filename(self, p):
            Path(p).write_bytes(self._data)

    class _Client:
        def list_blobs(self, bucket, prefix=None):
            return [_Blob(n, d) for n, d in files.items() if n.startswith(prefix or "")]

    class _Storage:
        def Client(self, *a, **k):  # noqa: N802 — mirrors storage.Client
            return _Client()

    monkeypatch.setitem(sys.modules, "google.cloud", type(sys)("google.cloud"))
    monkeypatch.setattr(sys.modules["google.cloud"], "storage", _Storage(), raising=False)


def test_sync_noop_off_gcs(monkeypatch):
    _make_gcs(monkeypatch, kind="local")
    assert rules_sync.sync_rules_from_gcs() == 0  # must not touch the SDK


def test_publish_noop_off_gcs(monkeypatch):
    _make_gcs(monkeypatch, kind="local")
    assert rules_sync.publish_rules_to_gcs() == 0


def test_sync_failure_is_swallowed(monkeypatch, tmp_path):
    _make_gcs(monkeypatch, data_root=tmp_path)
    _boom_storage(monkeypatch)
    # A GCS failure at boot must not propagate.
    assert rules_sync.sync_rules_from_gcs() == 0


def test_sync_pulls_and_writes_files(monkeypatch, tmp_path):
    _make_gcs(monkeypatch, data_root=tmp_path)
    _fake_storage(monkeypatch, {
        "rules/ultimate/rules.pdf": b"%PDF-1.7",
        "rules/hearts/rules-for-hearts.md": b"# Hearts",
        "rules/": b"",  # prefix placeholder — must be skipped
    })
    n = rules_sync.sync_rules_from_gcs()
    assert n == 2
    assert (tmp_path / "rules" / "ultimate" / "rules.pdf").read_bytes() == b"%PDF-1.7"
    assert (tmp_path / "rules" / "hearts" / "rules-for-hearts.md").read_text() == "# Hearts"
