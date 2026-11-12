# Copyright (c) 2026 Eric Cooper.
"""Rerankers: BM25, hybrid fusion, the selection knob, and the eval/retrieve seam."""

from __future__ import annotations

import pytest

from rulebook.rerank import (
    BM25Reranker,
    HybridReranker,
    make_reranker,
    reorder,
    tokenize,
)


def test_tokenize_keeps_hyphenated_words_and_drops_stopwords():
    assert tokenize("How many betting rounds are there in Seven-Card stud?") == [
        "many",
        "betting",
        "rounds",
        "seven-card",
        "stud",
    ]


def test_bm25_prefers_the_passage_sharing_the_rare_word():
    passages = [
        "The dealer deals five cards to each player.",
        "In Omaha each player gets four hole cards.",
        "The dealer burns a card before each street.",
    ]
    scores = BM25Reranker().rerank("How many hole cards in Omaha?", passages)
    assert scores.index(max(scores)) == 1
    assert scores[2] == 0.0  # no shared word ("card" isn't "cards": no stemming)


def test_bm25_term_frequency_saturates():
    one = BM25Reranker().rerank("razz", ["razz x x x", "y y y y"])[0]
    many = BM25Reranker().rerank("razz", ["razz razz razz razz", "y y y y"])[0]
    assert one < many < 4 * one  # more mentions help, with diminishing returns


def test_bm25_handles_no_passages():
    assert BM25Reranker().rerank("anything", []) == []


def test_hybrid_keeps_embedding_order_when_bm25_cannot_tell():
    passages = ["alpha", "beta", "gamma"]  # none shares a word with the question
    scores = HybridReranker().rerank("delta?", passages)
    assert scores == sorted(scores, reverse=True)


def test_hybrid_lifts_a_passage_bm25_ranks_first():
    # Embedding order puts the matching passage last; BM25 puts it first.
    passages = ["the board", "the pieces", "the opening", "kings move backward"]
    scores = HybridReranker().rerank("Can kings move backward?", passages)
    assert scores.index(max(scores)) in (0, 3)
    assert scores[3] > scores[1] and scores[3] > scores[2]


def test_reorder_sorts_by_score_and_is_stable_on_ties():
    class Fixed:
        name = "fixed"

        def rerank(self, question, passages):
            return [1.0, 3.0, 1.0, 2.0]

    assert reorder("q", ["a", "b", "c", "d"], ["", "", "", ""], Fixed()) == ["b", "d", "a", "c"]


def test_make_reranker_selection():
    assert make_reranker("none") is None
    assert make_reranker("bm25").name == "bm25"
    assert make_reranker("hybrid").name == "hybrid"
    with pytest.raises(ValueError):
        make_reranker("cohere")


def test_local_reranker_without_the_extra_says_how_to_install():
    try:
        import fastembed  # noqa: F401
    except ImportError:
        with pytest.raises(ImportError, match="rerank-local"):
            make_reranker("local")
    else:
        pytest.skip("fastembed is installed; the install hint isn't reachable")


def test_evaluate_with_a_reranker_reorders_within_the_candidates(monkeypatch, tmp_path):
    pytest.importorskip("model2vec")
    from rulebook.config import settings
    from rulebook.eval import build_scratch_index, evaluate, load_gold

    monkeypatch.setattr(settings, "index_path", tmp_path)
    model = "minishlab/potion-retrieval-32M"
    try:
        idx = build_scratch_index("poker", model)
    except Exception as e:  # noqa: BLE001 — model fetch failed (offline/rate-limited)
        pytest.skip(f"local model {model!r} unavailable: {e}")

    class Reverse:
        """Puts the embedding order upside down, so the effect is unmistakable."""

        name = "reverse"

        def rerank(self, question, passages):
            return list(range(len(passages)))

    items = load_gold("poker")[:3]
    plain = evaluate(items, k=5, index=idx)
    flipped = evaluate(items, k=5, index=idx, reranker=Reverse(), candidates=8)
    for p, f in zip(plain.items, flipped.items, strict=True):
        assert len(f.retrieved_ids) == 5
        # The reversed top 8 starts with the embedding's 8th and never includes its 1st-3rd.
        assert not set(p.retrieved_ids[:3]) & set(f.retrieved_ids)
