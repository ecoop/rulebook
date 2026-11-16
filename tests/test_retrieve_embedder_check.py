# Copyright (c) 2026 Eric Cooper.
"""Retrieval refuses an index built by a different embedder than the configured one."""

from __future__ import annotations

import json
import logging

import pytest

from rulebook import retrieve as retrieve_mod
from rulebook.chunking import Chunk
from rulebook.config import settings
from rulebook.retrieve import EmbedderMismatchError, retrieve, retrieve_across_domains
from rulebook.store import MANIFEST_FILE, domain_index_path, write_store

CONFIGURED = ("local", "minishlab/potion-retrieval-32M")


class _FakeEmbedder:
    def __init__(self):
        self.calls = 0

    def embed(self, texts, *, input_type):
        self.calls += 1
        return [[1.0, 0.0] for _ in texts]


@pytest.fixture
def env(tmp_path, monkeypatch):
    """An index root under tmp_path, the configured embedder pinned, a fake embedder."""
    monkeypatch.setattr(settings, "index_path", tmp_path)
    monkeypatch.setattr(settings, "embedding_provider", CONFIGURED[0])
    monkeypatch.setattr(settings, "embedding_model", CONFIGURED[1])
    fake = _FakeEmbedder()
    monkeypatch.setattr(retrieve_mod, "get_embedder", lambda: fake)
    monkeypatch.setattr(retrieve_mod, "_warned_unknown_embedder", set())
    assert settings.resolved_index_path == tmp_path
    return tmp_path, fake


def _build(root, domain, *, provider, model):
    chunk = Chunk(source="s.pdf", domain=domain, rule_id="1", page_start=1, page_end=1,
                  text="the stall count is ten")
    write_store(domain_index_path(root, domain), [chunk], [[1.0, 0.0]],
                provider=provider, model=model)


def test_matching_index_is_searched(env):
    root, _ = env
    _build(root, "ultimate", provider=CONFIGURED[0], model=CONFIGURED[1])
    [hit] = retrieve("stall?", domain="ultimate", reranker=None)
    assert hit.rule_id == "1"


def test_mismatched_model_raises_with_rebuild_command(env):
    root, fake = env
    _build(root, "ultimate", provider="local", model="minishlab/potion-base-8M")
    with pytest.raises(EmbedderMismatchError) as exc:
        retrieve("stall?", domain="ultimate", reranker=None)
    msg = str(exc.value)
    assert "local/minishlab/potion-base-8M" in msg          # what built the index
    assert f"{CONFIGURED[0]}/{CONFIGURED[1]}" in msg         # what is configured
    assert "uv run python scripts/build_index.py --domain ultimate" in msg
    assert fake.calls == 0  # refused before spending an embedding call


def test_mismatched_provider_raises(env):
    root, _ = env
    _build(root, "ultimate", provider="voyage", model=CONFIGURED[1])
    with pytest.raises(EmbedderMismatchError, match="voyage/"):
        retrieve("stall?", domain="ultimate", reranker=None)


def test_mismatch_is_a_runtime_error_so_the_api_returns_503(env):
    # api/main.py maps RuntimeError from ask() to a 503 carrying the message.
    assert issubclass(EmbedderMismatchError, RuntimeError)


def test_across_domains_raises_if_any_domain_mismatches(env):
    root, fake = env
    _build(root, "ultimate", provider=CONFIGURED[0], model=CONFIGURED[1])
    _build(root, "curling", provider="voyage", model="voyage-3.5")
    with pytest.raises(EmbedderMismatchError, match="'curling'"):
        retrieve_across_domains("stall?")
    assert fake.calls == 0


def test_across_domains_searches_when_all_match(env):
    root, _ = env
    _build(root, "ultimate", provider=CONFIGURED[0], model=CONFIGURED[1])
    _build(root, "curling", provider=CONFIGURED[0], model=CONFIGURED[1])
    assert {c.domain for c in retrieve_across_domains("stall?")} == {"ultimate", "curling"}


def test_manifest_without_model_is_searched_with_one_warning(env, caplog):
    root, _ = env
    _build(root, "ultimate", provider="x", model="y")
    mf = domain_index_path(root, "ultimate") / MANIFEST_FILE
    manifest = json.loads(mf.read_text())
    del manifest["provider"], manifest["model"]
    mf.write_text(json.dumps(manifest))

    with caplog.at_level(logging.WARNING, logger="rulebook.retrieve"):
        retrieve("stall?", domain="ultimate", reranker=None)
        [hit] = retrieve("stall?", domain="ultimate", reranker=None)
    assert hit.rule_id == "1"
    warnings = [r for r in caplog.records if "records no embedding model" in r.message]
    assert len(warnings) == 1


def test_index_with_no_manifest_file_is_searched(env):
    root, _ = env
    _build(root, "ultimate", provider="x", model="y")
    (domain_index_path(root, "ultimate") / MANIFEST_FILE).unlink()
    [hit] = retrieve("stall?", domain="ultimate", reranker=None)
    assert hit.rule_id == "1"
