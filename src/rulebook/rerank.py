# Copyright (c) 2026 Eric Cooper.
"""Reranking: a second, slower look at the passages retrieval found.

Retrieval embeds the question and each passage SEPARATELY and compares the two
vectors. Each passage's vector was made at index time, before any question
existed, so it can only say what the passage is *about*. A question about
seven-card stud's betting rounds lands next to Razz's rule "five betting rounds,
exactly as in seven-card stud": same topic, wrong game.

A reranker gets a second pass over a wider set of candidates (``candidates``,
default 20) and reorders them before the top ``k`` go to the answer model. Three
are built in, from cheapest to strongest:

    bm25     Word overlap (Okapi BM25): rare words the question shares with a
             passage count most. No model, no key; good at exact terms ("Omaha")
             that embeddings blur. It still compares words, not meaning.

    hybrid   Fuses the embedding order with the BM25 order (reciprocal rank
             fusion), so a passage needs to do well on both to rise.

    local    A cross-encoder: one small transformer reads the question and the
             passage TOGETHER, as one input, and outputs a relevance score. Every
             question word can attend to every passage word, which is what it
             takes to tell "answers it" from "about it". Nothing can be computed
             ahead of time, so it runs once per (question, candidate) pair; that is
             why it only reranks a short list. Runs on ONNX via fastembed, an
             optional extra: ``uv sync --extra rerank-local`` (no wheels for Intel
             Macs; Linux, Apple Silicon, Windows and Colab are fine).

Every reranker has the same shape (:class:`Reranker`): given the question and the
candidate passages in retrieval order, return one score per passage, higher =
better. Selected by RERANK_PROVIDER (none|bm25|hybrid|local); the default, none,
leaves retrieval exactly as it was.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Protocol

from .config import settings

DEFAULT_CROSS_ENCODER = "Xenova/ms-marco-MiniLM-L-6-v2"


class Reranker(Protocol):
    name: str

    def rerank(self, question: str, passages: list[str]) -> list[float]:
        """One score per passage (higher = better). ``passages`` arrive in
        first-stage (embedding) order, which the hybrid reranker relies on."""
        ...


def reorder(question: str, items: list, texts: list[str], reranker: Reranker) -> list:
    """``items`` sorted by ``reranker``'s scores for ``texts`` (stable on ties)."""
    scores = reranker.rerank(question, texts)
    order = sorted(range(len(items)), key=lambda i: -scores[i])
    return [items[i] for i in order]


# --- BM25 -------------------------------------------------------------------

# Function words that carry no topic. Kept short on purpose: BM25's IDF already
# discounts words that appear everywhere, this just keeps "how/do/you" from
# counting as matches.
_STOPWORDS = frozenset(
    "a an and are as at be by can do does for from how i in is it its my of on or "
    "the their there these this to what when where which who why with you your".split()
)
_WORD = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def tokenize(text: str) -> list[str]:
    """Lowercase words (hyphenated words stay whole: "seven-card"), minus stopwords."""
    return [w for w in _WORD.findall(text.lower()) if w not in _STOPWORDS]


class BM25Reranker:
    """Okapi BM25 over the candidates. For each question word found in a passage:

        idf(word) * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len / avg_len))

    summed over the question's words. ``idf`` is high for words few passages use,
    ``tf`` (term frequency) saturates via ``k1`` so repeating a word ten times
    doesn't score ten times higher, and ``b`` discounts long passages. The idf is
    computed over the candidates passed in, so it needs no index of its own.
    """

    name = "bm25"

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b

    def rerank(self, question: str, passages: list[str]) -> list[float]:
        docs = [tokenize(p) for p in passages]
        if not docs:
            return []
        n = len(docs)
        avg_len = sum(map(len, docs)) / n or 1.0
        df = Counter(w for d in docs for w in set(d))
        q_words = tokenize(question)
        scores = []
        for d in docs:
            tf = Counter(d)
            norm = self.k1 * (1 - self.b + self.b * len(d) / avg_len)
            s = 0.0
            for w in q_words:
                if w in tf:
                    idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
                    s += idf * tf[w] * (self.k1 + 1) / (tf[w] + norm)
            scores.append(s)
        return scores


# --- Hybrid -----------------------------------------------------------------


class HybridReranker:
    """Reciprocal rank fusion of the embedding order and the BM25 order.

    Each list gives a passage ``1 / (c + rank)``; the two are summed. Using ranks
    rather than raw scores sidesteps the two scores' different scales. ``c = 60``
    is the constant from the original RRF paper; it keeps a single first place
    from outweighing two good-but-not-first places.
    """

    name = "hybrid"

    def __init__(self, c: int = 60):
        self.c = c
        self.bm25 = BM25Reranker()

    def rerank(self, question: str, passages: list[str]) -> list[float]:
        bm = self.bm25.rerank(question, passages)
        bm_rank = {i: r for r, i in enumerate(sorted(range(len(passages)), key=lambda i: -bm[i]))}
        # Passages arrive in embedding order, so the embedding rank is the index.
        return [1 / (self.c + i) + 1 / (self.c + bm_rank[i]) for i in range(len(passages))]


# --- Cross-encoder ----------------------------------------------------------


class CrossEncoderReranker:
    """A cross-encoder run locally on ONNX (fastembed's TextCrossEncoder).

    The default, ms-marco-MiniLM-L-6-v2 (~80 MB, downloaded once and cached), was
    trained on MS MARCO: real search queries paired with the passages that answer
    them. Its score is a logit, so only the order matters, not the scale.
    """

    def __init__(self, model: str = DEFAULT_CROSS_ENCODER):
        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
        except ImportError as e:  # pragma: no cover - depends on the optional extra
            raise ImportError(
                "The local cross-encoder needs the rerank-local extra: "
                "`uv sync --extra rerank-local` (or `pip install fastembed`). "
                "onnxruntime has no wheels for Intel Macs; use bm25/hybrid there, "
                "or run the notebook in Colab."
            ) from e
        self.name = f"cross-encoder ({model.split('/')[-1]})"
        self.model = model
        self._encoder = TextCrossEncoder(model_name=model)

    def rerank(self, question: str, passages: list[str]) -> list[float]:
        return [float(s) for s in self._encoder.rerank(question, passages)]


# --- Selection --------------------------------------------------------------


def make_reranker(provider: str, model: str | None = None) -> Reranker | None:
    """``none`` → None; ``bm25`` / ``hybrid`` / ``local`` → that reranker."""
    if provider == "none":
        return None
    if provider == "bm25":
        return BM25Reranker()
    if provider == "hybrid":
        return HybridReranker()
    if provider == "local":
        return CrossEncoderReranker(model or DEFAULT_CROSS_ENCODER)
    raise ValueError(f"unknown rerank provider {provider!r} (none|bm25|hybrid|local)")


_cached: tuple[tuple[str, str], Reranker | None] | None = None


def get_reranker() -> Reranker | None:
    """The reranker RERANK_PROVIDER selects (None by default), built once."""
    global _cached
    key = (settings.rerank_provider, settings.rerank_model)
    if _cached is None or _cached[0] != key:
        _cached = (key, make_reranker(*key))
    return _cached[1]
