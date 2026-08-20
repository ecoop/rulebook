# Copyright (c) 2026 Eric Cooper.
"""Chunk text is whitespace-normalized (pypdf's word-per-line → prose)."""

from __future__ import annotations

from rulebook.chunking import (
    _detect_numbered_title_anchors,
    _normalize_ws,
    chunk_pages,
)
from rulebook.ingest import PageText


def test_normalize_ws_collapses_word_per_line():
    # The pypdf failure mode: a text page extracted one word per line.
    raw = "Pivot: the body in contact\nduring\n \na\n \nthrower's\n \npossession"
    assert _normalize_ws(raw) == "Pivot: the body in contact during a thrower's possession"


def test_normalize_ws_double_spaces_and_edges():
    assert _normalize_ws("  a  b\t\tc  ") == "a b c"


def test_normalize_ws_clean_prose_unchanged():
    s = "The thrower must establish a pivot."
    assert _normalize_ws(s) == s


# --- numbered-title anchors (World Curling "R13. INTERRUPTED GAMES" style) ---


def test_numbered_title_matches_inline_caps_title():
    # Matched anywhere (extraction flattens these off the line start), keyed on
    # the ALL-CAPS title; a prose cross-reference ("see R6. The …") must NOT match.
    text = "... play continues. R6. FREE GUARD ZONE No stone in the ... see R6. The zone is ..."
    ids = [rid for _off, rid in _detect_numbered_title_anchors(text)]
    assert ids == ["R6"]  # the cross-reference "R6. The" is excluded


def test_numbered_title_dedupes_toc_keeping_body():
    # The table of contents lists the rule first; the body definition is last.
    text = "R6. FREE GUARD ZONE ..... 12   [body follows] R6. FREE GUARD ZONE No stone ..."
    anchors = _detect_numbered_title_anchors(text)
    assert [rid for _o, rid in anchors] == ["R6"]
    assert anchors[0][0] == text.rindex("R6. FREE GUARD ZONE")  # kept the body offset


def test_chunk_pages_anchors_r_number_rules():
    # Needs >= MIN_ANCHORS_TO_TRUST (5) distinct rules for the strategy to fire.
    body = (
        "THE SPIRIT OF CURLING Curling is a game of skill and tradition played on ice. "
        " R1. SHEET The playing surface shall be rectangular with the dimensions specified in these rules. "
        " R2. STONES Each stone shall be of a specified weight and shall be made of the approved material. "
        " R3. TEAMS A team consists of four players, each of whom delivers two stones per end in sequence. "
        " R4. POSITION OF PLAYERS Players shall stand as directed by these rules while a stone is delivered. "
        " R5. DELIVERY A stone must be clearly released from the hand before it reaches the nearer hog line. "
        " R6. FREE GUARD ZONE A stone in the free guard zone shall not be removed from play by the opposition. "
        " R7. SCORING A team scores one point for each of its stones nearer to the button than any opponent's. "
    )
    chunks = chunk_pages([PageText(page_number=1, text=body)], source="c.pdf", domain="curling")
    ids = {c.rule_id for c in chunks}
    assert {"R1", "R5", "R6", "R7"} <= ids
    # the free-guard-zone text is attributed to R6, not lumped into a preamble
    fgz = [c for c in chunks if "free guard zone" in c.text.lower()]
    assert fgz and all(c.rule_id == "R6" for c in fgz)
