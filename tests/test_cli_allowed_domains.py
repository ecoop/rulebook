# Copyright (c) 2026 Eric Cooper.
"""The allowed_domains CLI sees the same users the app does — env seed ⊕ GCS."""

from __future__ import annotations

import json

import pytest

import scripts.allowed_domains as ad


def test_all_invite_tokens_merges_env_seed(monkeypatch):
    # Env-seed users (baked into the deploy) must be visible to list/backfill,
    # not just the GCS-object users; GCS wins on a token collision.
    monkeypatch.setenv(
        "RULEBOOK_INVITE_TOKENS", json.dumps({"tok_env": "Emeric", "tok_dup": "seed"})
    )
    monkeypatch.setattr(ad, "read_tokens_object", lambda _b, _o: {"tok_gcs": "Adam", "tok_dup": "gcs"})
    merged = ad._all_invite_tokens("bucket")
    assert merged["tok_env"] == "Emeric"   # env-seed user now visible
    assert merged["tok_gcs"] == "Adam"     # gcs-object user visible
    assert merged["tok_dup"] == "gcs"      # GCS overrides the seed on conflict


def test_all_invite_tokens_no_seed(monkeypatch):
    monkeypatch.delenv("RULEBOOK_INVITE_TOKENS", raising=False)
    monkeypatch.setattr(ad, "read_tokens_object", lambda _b, _o: {"tok_gcs": "Adam"})
    assert ad._all_invite_tokens("bucket") == {"tok_gcs": "Adam"}


def test_all_invite_tokens_bad_json_exits(monkeypatch):
    monkeypatch.setenv("RULEBOOK_INVITE_TOKENS", "{not json")
    monkeypatch.setattr(ad, "read_tokens_object", lambda _b, _o: {})
    with pytest.raises(SystemExit):
        ad._all_invite_tokens("bucket")
