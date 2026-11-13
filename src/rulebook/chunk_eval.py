# Copyright (c) 2026 Eric Cooper.
"""Compare ways of cutting a rulebook into chunks, fairly.

hit@k (see eval.py) asks whether a cited rule is *somewhere in* the top k chunks.
That's the right question for one chunker, but it can't compare chunkers: a bigger
chunk holds more rules, so it "hits" more often while handing Claude more to read.
Cut a rulebook into one chunk and every question scores hit@1 = 1.0.

So this module scores every way of cutting on the same footing:

    reading budget   Take chunks in retrieval order until ``budget`` characters
                     are filled (the last one cut short). Did any of that text
                     overlap a cited rule? That's a hit.
    cited share      What fraction of the budget *is* a cited rule. A chunker that
                     hits by handing over whole sections scores low here.

A "cut" is just a list of (start, end) character windows over the domain's text,
so any chunker can be scored: the app's rule chunks (``rule_spans``), whole
sections (``section_windows``) or naive fixed-size windows (``fixed_windows``).
Which rule a window covers comes from where the app's own rule chunks sit in the
text. notebooks/chunking.ipynb walks through it on the sample rule sets.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .chunking import Chunk, _normalize_ws
from .eval import GoldItem


@dataclass(frozen=True)
class Span:
    """Where one rule chunk sits in the domain's text: ``text[start:end]``."""

    start: int
    end: int
    rule_id: str


def rule_spans(text: str, chunks: list[Chunk]) -> list[Span]:
    """Locate each chunk (in order) in ``text``, the whitespace-normalised document.

    Chunks must be cut without section headers, so their text appears verbatim.
    """
    spans: list[Span] = []
    pos = 0
    for c in chunks:
        i = text.find(c.text, pos)
        if i < 0:
            raise ValueError(f"chunk {c.rule_id!r} isn't in the text (section headers on?)")
        spans.append(Span(i, i + len(c.text), c.rule_id))
        pos = i + len(c.text)
    return spans


def document_text(pages_text: list[str]) -> str:
    """The text the chunker saw, whitespace-normalised so chunk text is a substring."""
    return _normalize_ws(" ".join(pages_text))


def fixed_windows(text: str, size: int) -> list[tuple[int, int]]:
    """Cut ``text`` every ``size`` characters, backing up to a space: the naive chunker."""
    out: list[tuple[int, int]] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            space = text.rfind(" ", start + 1, end)
            end = space if space > start else end
        out.append((start, end))
        start = end + 1 if end < len(text) and text[end] == " " else end
    return out


def section_windows(spans: list[Span]) -> list[tuple[int, int]]:
    """One window per top-level rule number ("3.1" .. "3.6" -> section 3)."""
    groups: dict[str, tuple[int, int]] = {}
    for s in spans:
        key = s.rule_id.split(".")[0]
        a, b = groups.get(key, (s.start, s.end))
        groups[key] = (min(a, s.start), max(b, s.end))
    return sorted(groups.values())


@dataclass
class CutScore:
    name: str
    chunks: int
    hits_at_1: int        # per-chunk view: a cited rule overlaps the first chunk
    chars_at_1: int       # ... and how much text that first chunk is, on average
    budget: int
    budget_hits: int      # fair view: a cited rule overlaps the first ``budget`` chars
    cited_share: float    # ... and the share of those chars that are a cited rule
    n: int


def score_cut(
    name: str,
    windows: list[tuple[int, int]],
    text: str,
    spans: list[Span],
    gold: list[GoldItem],
    embedder,
    *,
    budget: int = 500,
) -> CutScore:
    """Embed each window, retrieve for each gold question, and score both views."""
    texts = [text[a:b] for a, b in windows]
    vecs = np.asarray(embedder.embed(texts, input_type="document"), dtype=np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    hits1 = chars1 = budget_hits = 0
    share = 0.0
    for g in gold:
        cited = [(s.start, s.end) for s in spans if s.rule_id in g.rule_ids]
        q = np.asarray(embedder.embed([g.question], input_type="query")[0], dtype=np.float32)
        order = np.argsort(-(vecs @ (q / np.linalg.norm(q))), kind="stable")

        a, b = windows[order[0]]
        hits1 += any(a < e and s < b for s, e in cited)
        chars1 += b - a

        taken, left = [], budget
        for i in order:
            a, b = windows[i]
            take = min(b - a, left)
            taken.append((a, a + take))
            left -= take
            if left <= 0:
                break
        budget_hits += any(a < e and s < b for a, b in taken for s, e in cited)
        overlap = sum(max(0, min(b, e) - max(a, s)) for a, b in taken for s, e in cited)
        share += overlap / budget
    n = len(gold)
    return CutScore(
        name=name,
        chunks=len(windows),
        hits_at_1=hits1,
        chars_at_1=round(chars1 / n) if n else 0,
        budget=budget,
        budget_hits=budget_hits,
        cited_share=share / n if n else 0.0,
        n=n,
    )
