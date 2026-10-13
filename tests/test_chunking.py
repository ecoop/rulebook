# Copyright (c) 2026 Eric Cooper.
"""Chunk text is whitespace-normalized (pypdf's word-per-line → prose)."""

from __future__ import annotations

from rulebook.chunking import (
    MAX_CHARS,
    _detect_hierarchical_anchors,
    _detect_markdown_heading_anchors,
    _detect_numbered_title_anchors,
    _normalize_ws,
    _split_if_long,
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


# --- markdown-heading anchors (authored prose rules: hearts, backgammon) -----


def test_markdown_headings_detected_as_anchors():
    text = "# Hearts\nIntro.\n## The Deal\nDeal 13 each.\n### Passing\nPass three.\n## Scoring\nHearts are 1 point."
    ids = [rid for _off, rid in _detect_markdown_heading_anchors(text)]
    assert ids == ["Hearts", "The Deal", "Passing", "Scoring"]


def test_chunk_pages_splits_markdown_by_section():
    # A prose doc with no rule-numbering scheme should chunk per ## section,
    # with the heading text as the rule_id (section-based citation).
    md = (
        "# Backgammon\nBackgammon is a two-player race game combining dice and "
        "strategy; each player moves fifteen checkers around and off the board.\n\n"
        "## The Setup\nEach player has fifteen checkers in the starting position.\n\n"
        "## Bearing Off\nOnce all checkers are home, remove them by dice roll.\n\n"
        "## The Doubling Cube\nEither player may propose to double the stakes.\n"
    )
    chunks = chunk_pages([PageText(page_number=1, text=md)], source="bg.md", domain="backgammon")
    ids = [c.rule_id for c in chunks]
    assert ids == ["Backgammon", "The Setup", "Bearing Off", "The Doubling Cube"]
    bearing = [c for c in chunks if c.rule_id == "Bearing Off"]
    assert bearing and "dice roll" in bearing[0].text


def test_markdown_headings_ignored_when_numbering_present():
    # A numbered rulebook that also contains a markdown-ish '#' line must still
    # chunk by its rule numbers — heading detection is a fallback only.
    body = (
        "# Title line that should not become an anchor "
        " R1. SHEET The playing surface is rectangular as specified in these rules. "
        " R2. STONES Each stone is of the specified weight and approved material used in play. "
        " R3. TEAMS A team is four players, each delivering two stones per end in sequence. "
        " R4. POSITION Players stand as directed by these rules while a stone is delivered. "
        " R5. DELIVERY A stone must be released from the hand before it reaches the hog line. "
    )
    chunks = chunk_pages([PageText(page_number=1, text=body)], source="c.pdf", domain="curling")
    ids = {c.rule_id for c in chunks}
    assert {"R1", "R2", "R3", "R4", "R5"} <= ids
    assert not any("Title line" == c.rule_id for c in chunks)


# --- hierarchical (Roman / letter / digit) anchors: USAG Goaltimate style ----


def _hier_ids(text: str) -> list[str]:
    return [rid for _off, rid in _detect_hierarchical_anchors(text)]


def test_five_char_roman_section_is_detected():
    # "XVIII." was beyond a 4-char cap, so the whole section was filed under XVII.
    text = (
        "XVII. Screens\nA. A screen is defined.\n"
        "XVIII. Violations & Fouls\nK. Goaltending: Players entering.\n"
        "1. Goaltending Count: If a player delays.\n"
    )
    assert _hier_ids(text) == ["XVII", "XVII.A", "XVIII", "XVIII.K", "XVIII.K.1"]


def test_toc_entries_do_not_capture_the_body():
    # A TOC ending at "XXI." made the body's "I. Introduction" read as letter I
    # of section XXI (rule id XXI.I) instead of section I.
    toc = "I. Introduction 3\nII. Spirit of the Game 3\nXXI. Etiquette 42\n"
    body = "I. Introduction\nA. Description: Goaltimate is a disc sport.\n"
    ids = _hier_ids(toc + body)
    assert "I.A" in ids and not any(r.startswith("XXI") for r in ids)


def test_toc_dot_leaders_are_recognized():
    text = "XX. Game Officials ........ 41\nXXI. Etiquette .......... 42\nI. Introduction\nA. Rules.\n"
    assert _hier_ids(text) == ["I", "I.A"]


def test_letter_continuing_sequence_beats_roman():
    # In section IV, "V." right after "U." is the next letter, not section V.
    text = "IV. Field\nU. The penultimate letter.\nV. The next letter.\n"
    assert _hier_ids(text)[-1] == "IV.V"


def test_appendix_is_top_level_but_cross_reference_is_not():
    text = (
        "II. Spirit\nD. For behavior warranting sanctions pursuant to\n"
        "Appendix B: Guidelines to Misconduct, captains act.\n"
        "XXI. Etiquette\nB. Avoid delay.\n"
        "Appendix B: Guidelines for Misconduct\nB. Fighting: The following acts.\n"
    )
    ids = _hier_ids(text)
    # The mid-sentence mention doesn't open a section; the real heading does, so
    # its B. no longer overwrites (via keep-last dedupe) Etiquette's XXI.B.
    assert ids == ["II", "II.D", "XXI", "XXI.B", "Appendix B", "Appendix B.B"]


def test_appendix_ignored_without_roman_sections():
    # Digit-sectioned rulebooks (Official Rules of Ultimate) list appendices too;
    # treating them as a parent would re-parent every later numbered rule.
    text = "Appendix A: Field Diagram\n1. Introduction\n2. Spirit of the Game\n"
    assert _hier_ids(text) == ["1", "2"]


# --- splitting an over-long section ----------------------------------------


def test_split_long_section_breaks_at_sentence_ends():
    # pypdf's word-per-paragraph output made every word a "paragraph", so the old
    # paragraph packer cut mid-sentence ("…count reaches" | "three, this is…").
    sentence = "When the goaltending count reaches three this is a goaltending violation."
    text = "\n\n".join(" ".join([sentence] * 40).split(" "))  # one word per paragraph
    pieces = _split_if_long(text)
    assert len(pieces) > 1
    assert all(len(p) <= MAX_CHARS and p.endswith("violation.") for p in pieces)
    assert " ".join(pieces) == _normalize_ws(text)


def test_split_keeps_annotation_brackets_with_their_sentence():
    text = ("A rule applies. [[An annotation explains it.]] " * 60).strip()
    pieces = _split_if_long(text)
    assert len(pieces) > 1
    # Never split between a sentence's period and its closing "]]".
    assert not any(p.startswith("]]") or p.endswith("it.") for p in pieces)


def test_split_word_cuts_an_oversize_sentence():
    text = "word " * 1000  # one 5000-char "sentence" with no terminator
    pieces = _split_if_long(text)
    assert len(pieces) > 1 and all(len(p) <= MAX_CHARS for p in pieces)
    assert " ".join(pieces) == _normalize_ws(text)
