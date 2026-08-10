# Copyright (c) 2026 Eric Cooper.
"""Tests for the invite-token source (merge / TTL cache / failure fallback).

No real GCS: we stub the object read so the value under test is the
seed+overrides merge policy and the cache/refresh contract.
"""

from __future__ import annotations

import pytest

import rulebook.tokens as tokens


@pytest.fixture(autouse=True)
def _clear_cache():
    tokens._overrides_cache.clear()
    yield
    tokens._overrides_cache.clear()


@pytest.fixture
def clock(monkeypatch):
    """Controllable monotonic clock so TTL expiry is deterministic."""
    now = {"t": 1000.0}
    monkeypatch.setattr(tokens.time, "monotonic", lambda: now["t"])
    return now


def _stub_read(monkeypatch, value, counter=None):
    def _read(bucket, object_name):
        if counter is not None:
            counter.append((bucket, object_name))
        if isinstance(value, Exception):
            raise value
        return dict(value)

    monkeypatch.setattr(tokens, "read_tokens_object", _read)


def test_local_returns_seed_only(monkeypatch):
    reads: list = []
    _stub_read(monkeypatch, {"tok_gcs": "from-gcs"}, reads)
    out = tokens.get_invite_tokens(
        kind="local", bucket="b", object_name="o", seed={"tok_seed": "eric"}
    )
    assert out == {"tok_seed": "eric"}
    assert reads == []  # local never touches GCS


def test_gcs_merges_object_over_seed(monkeypatch, clock):
    _stub_read(monkeypatch, {"tok_a": "alice", "tok_seed": "overridden"})
    out = tokens.get_invite_tokens(
        kind="gcs", bucket="b", object_name="o", seed={"tok_seed": "seed-label"}
    )
    assert out == {"tok_seed": "overridden", "tok_a": "alice"}


def test_ttl_caches_reads(monkeypatch, clock):
    reads: list = []
    _stub_read(monkeypatch, {"tok_a": "alice"}, reads)
    kw = dict(kind="gcs", bucket="b", object_name="o", seed={}, ttl_seconds=30.0)

    tokens.get_invite_tokens(**kw)
    clock["t"] += 10  # within TTL
    tokens.get_invite_tokens(**kw)
    assert len(reads) == 1  # served from cache

    clock["t"] += 25  # now past the 30s window
    tokens.get_invite_tokens(**kw)
    assert len(reads) == 2  # refreshed


def test_failure_reuses_last_good(monkeypatch, clock):
    _stub_read(monkeypatch, {"tok_a": "alice"})
    kw = dict(kind="gcs", bucket="b", object_name="o", seed={"tok_s": "s"}, ttl_seconds=1.0)
    assert tokens.get_invite_tokens(**kw) == {"tok_s": "s", "tok_a": "alice"}

    clock["t"] += 5  # expire, then fail the refresh
    _stub_read(monkeypatch, RuntimeError("gcs down"))
    out = tokens.get_invite_tokens(**kw)
    assert out == {"tok_s": "s", "tok_a": "alice"}  # last-good overrides kept


def test_cold_start_failure_falls_back_to_seed(monkeypatch, clock):
    _stub_read(monkeypatch, RuntimeError("gcs down"))
    out = tokens.get_invite_tokens(
        kind="gcs", bucket="b", object_name="o", seed={"tok_s": "s"}
    )
    assert out == {"tok_s": "s"}
