# Copyright (c) 2026 Eric Cooper.
"""Scoring ways of cutting a rulebook: windows, spans, and the budget view."""

from __future__ import annotations

import pytest

from rulebook.chunk_eval import (
    Span,
    fixed_windows,
    rule_spans,
    score_cut,
    section_windows,
)
from rulebook.chunking import Chunk
from rulebook.eval import GoldItem


def test_fixed_windows_cover_the_text_and_cut_at_spaces():
    text = "alpha beta gamma delta epsilon zeta eta theta"
    windows = fixed_windows(text, 12)
    assert all(b - a <= 12 for a, b in windows)
    assert " ".join(text[a:b] for a, b in windows) == text  # nothing lost, no word split


def test_section_windows_group_by_top_level_number():
    spans = [Span(0, 10, "1.1"), Span(11, 20, "1.2"), Span(21, 30, "2.1")]
    assert section_windows(spans) == [(0, 20), (21, 30)]


def _chunk(rule_id, text):
    return Chunk(source="x.md", domain="x", rule_id=rule_id, page_start=1, page_end=1, text=text)


def test_rule_spans_locate_chunks_and_refuse_prefixed_text():
    text = "1.1 Kings move. 1.2 Men move forward."
    spans = rule_spans(text, [_chunk("1.1", "1.1 Kings move."), _chunk("1.2", "1.2 Men move forward.")])
    assert [(text[s.start:s.end], s.rule_id) for s in spans] == [
        ("1.1 Kings move.", "1.1"),
        ("1.2 Men move forward.", "1.2"),
    ]
    with pytest.raises(ValueError, match="section headers"):
        rule_spans(text, [_chunk("1.1", "Checkers: 1.1 Kings move.")])


class KeywordEmbedder:
    """One dimension per keyword, so retrieval is predictable."""

    WORDS = ("king", "men", "board")

    def embed(self, texts, *, input_type):
        return [[float(w in t.lower()) + 1e-3 for w in self.WORDS] for t in texts]


def test_score_cut_counts_a_hit_and_the_cited_share():
    text = "1.1 The board is square. 1.2 A king moves both ways. 1.3 Men move forward."
    chunks = [
        _chunk("1.1", "1.1 The board is square."),
        _chunk("1.2", "1.2 A king moves both ways."),
        _chunk("1.3", "1.3 Men move forward."),
    ]
    spans = rule_spans(text, chunks)
    gold = [GoldItem(domain="x", question="How does a king move?", citations=("x 1.2",))]
    windows = [(s.start, s.end) for s in spans]
    score = score_cut("rule", windows, text, spans, gold, KeywordEmbedder(), budget=27)
    assert (score.hits_at_1, score.chars_at_1) == (1, 27)
    assert score.budget_hits == 1 and score.cited_share == pytest.approx(1.0)

    # One chunk always "hits" at rank 1, but a 24-char budget reads only rule 1.1.
    whole = score_cut("one chunk", [(0, len(text))], text, spans, gold, KeywordEmbedder(), budget=24)
    assert whole.hits_at_1 == 1 and whole.budget_hits == 0
