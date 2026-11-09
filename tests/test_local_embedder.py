# Copyright (c) 2026 Eric Cooper.
"""The local (model2vec) embedder — the key-free default.

model2vec is a core dependency, so this runs in CI; it downloads the default
model once (cached under ~/.cache/huggingface) and is skipped if that fetch
can't happen (offline / rate-limited), so a network hiccup never reds the build.

It checks the two things retrieval depends on: fixed-length vectors (one shared
dimension) and unit normalization, so the store's cosine-as-dot-product holds.
Static embeddings are symmetric, so there's no query/document asymmetry to test.
"""

from __future__ import annotations

import math

import pytest

pytest.importorskip("model2vec")

from rulebook.embeddings import LocalEmbedder  # noqa: E402 — after importorskip

MODEL = "minishlab/potion-retrieval-32M"  # the configured default


@pytest.fixture(scope="module")
def embedder() -> LocalEmbedder:
    try:
        return LocalEmbedder(MODEL)
    except Exception as e:  # noqa: BLE001 — model fetch failed (offline/rate-limited)
        pytest.skip(f"local model {MODEL!r} unavailable: {e}")


def test_returns_fixed_length_unit_vectors(embedder: LocalEmbedder) -> None:
    vecs = embedder.embed(
        ["the king is crowned", "bags are tossed at a board", "stalling counts"],
        input_type="document",
    )
    assert len(vecs) == 3
    dims = {len(v) for v in vecs}
    assert len(dims) == 1 and dims.pop() > 0, "all vectors must share one positive dimension"
    # Unit length → the store's cosine similarity reduces to a plain dot product.
    for v in vecs:
        assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, abs_tol=1e-3)


def test_query_and_document_paths_both_work(embedder: LocalEmbedder) -> None:
    # Static models are symmetric: input_type is accepted but doesn't change the
    # geometry. Both paths must return a vector of the same dimension.
    [as_doc] = embedder.embed(["how do you win the game?"], input_type="document")
    [as_query] = embedder.embed(["how do you win the game?"], input_type="query")
    assert len(as_doc) == len(as_query) > 0
