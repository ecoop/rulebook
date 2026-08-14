# Copyright (c) 2026 Eric Cooper.
"""Retrieval seam — chunk whitespace normalization."""

from __future__ import annotations

from rulebook.retrieve import _normalize_ws, _row_to_chunk


def test_normalize_ws_collapses_per_word_newlines():
    # The failure mode from the field-setup PDF: one word per line.
    raw = "L. Pivot: in continuous contact\nduring\n\na\n\nthrower's\n\npossession"
    assert _normalize_ws(raw) == (
        "L. Pivot: in continuous contact during a thrower's possession"
    )


def test_normalize_ws_leaves_clean_prose_untouched():
    clean = "The thrower must establish a pivot foot."
    assert _normalize_ws(clean) == clean


def test_normalize_ws_strips_edges_and_tabs():
    assert _normalize_ws("  a\t\tb \n c  ") == "a b c"


def test_row_to_chunk_normalizes_text():
    row = {
        "text": "one\n\ntwo\n\nthree",
        "source": "goaltimate",
        "sport": "goaltimate",
        "rule_id": "III.L",
        "page_start": "8",
        "page_end": "8",
        "_distance": "1.52",
    }
    chunk = _row_to_chunk(row)
    assert chunk.text == "one two three"
    assert chunk.rule_id == "III.L"
    assert chunk.page_start == 8
    assert chunk.distance == 1.52
