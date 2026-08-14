# Copyright (c) 2026 Eric Cooper.
"""Chunk text is whitespace-normalized (pypdf's word-per-line → prose)."""

from __future__ import annotations

from rulebook.chunking import _normalize_ws


def test_normalize_ws_collapses_word_per_line():
    # The pypdf failure mode: a text page extracted one word per line.
    raw = "Pivot: the body in contact\nduring\n \na\n \nthrower's\n \npossession"
    assert _normalize_ws(raw) == "Pivot: the body in contact during a thrower's possession"


def test_normalize_ws_double_spaces_and_edges():
    assert _normalize_ws("  a  b\t\tc  ") == "a b c"


def test_normalize_ws_clean_prose_unchanged():
    s = "The thrower must establish a pivot."
    assert _normalize_ws(s) == s
