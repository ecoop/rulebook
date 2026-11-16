# Copyright (c) 2026 Eric Cooper.
"""Rules numbered as titles ("R1. SHEET") with (a)/(b) clauses and caps sections."""

from __future__ import annotations

from rulebook.chunking import _parent_id, chunk_pages
from rulebook.generate import find_unverified_citations
from rulebook.ingest import PageText
from rulebook.retrieve import RetrievedChunk

TOC = "".join(
    f"R{n}. {title} {'.' * 40} {n + 3}\n"
    for n, title in enumerate(["SHEET", "STONES", "TEAMS", "DELIVERY", "SWEEPING"], start=1)
)

# Each clause is long enough that a rule and all its clauses don't fit one chunk.
FILLER = "The umpire decides any dispute about this clause before play continues. " * 4

BODY = f"""THE RULES OF CURLING
These rules apply to any game to which they are made applicable.
R1. SHEET
(a) The sheet is a rectangle of ice. {FILLER}
(b) Lines are marked across the sheet as follows:
I. the tee line, through the centre of the house.
II. the hog line, a fixed distance from the tee line.
44.501 m. is the shortest length allowed.
(c) Hacks are placed on the hack line. {FILLER}
R2. STONES
(a) A stone is round and of a fixed weight. {FILLER}
(b) A stone that stops short of the hog line is removed from play. {FILLER}
R3. TEAMS
(a) A team has four players. {FILLER}
(b) If the criteria in
(i) or (ii) are equal, the teams draw lots. {FILLER}
R4. DELIVERY
(a) A stone is released before the hog line. {FILLER}
R5. SWEEPING
(a) Any player of the delivering team may sweep. {FILLER}
GLOSSARY OF TERMS
Hog Line A line across the sheet, parallel to each tee line.
Hogged Stone A stone removed for stopping short of the hog line.
"""


def _chunks(**kw):
    pages = [PageText(page_number=1, text=TOC), PageText(page_number=2, text=BODY)]
    return chunk_pages(pages, source="c.pdf", domain="curling", **kw)


def test_clauses_are_anchors_under_their_rule():
    # Unmerged, so each clause shows as its own anchor ("R1. SHEET" alone is too
    # short to keep).
    ids = [c.rule_id for c in _chunks(merge_chars=0)]
    assert ids[ids.index("R1(a)") : ids.index("R3(a)")] == ["R1(a)", "R1(b)", "R1(c)", "R2(a)", "R2(b)"]


def test_a_roman_list_stays_inside_its_clause():
    chunks = _chunks(merge_chars=0)
    [lines] = [c for c in chunks if c.rule_id == "R1(b)"]
    assert "I. the tee line" in lines.text and "II. the hog line" in lines.text
    assert not any(c.rule_id in ("I", "II") or c.rule_id.endswith(".I") for c in chunks)


def test_a_parenthesized_cross_reference_is_not_a_clause():
    chunks = _chunks(merge_chars=0)
    assert "R3(i)" not in [c.rule_id for c in chunks]
    [b] = [c for c in chunks if c.rule_id == "R3(b)"]
    assert "(i) or (ii) are equal" in b.text


def test_a_measurement_at_a_line_start_is_not_a_rule():
    assert "44.501" not in [c.rule_id for c in _chunks()]


def test_table_of_contents_entries_are_neither_anchors_nor_text():
    chunks = _chunks()
    assert [c.rule_id for c in chunks].count("R1") == 1
    assert not any("....." in c.text for c in chunks)


def test_an_unnumbered_caps_section_is_named_by_its_heading():
    [glossary] = [c for c in _chunks() if c.rule_id == "GLOSSARY OF TERMS"]
    assert glossary.text.startswith("GLOSSARY OF TERMS Hog Line A line across the sheet")
    # ... so a definition is not cited as the last numbered clause before it.
    assert all("Hogged Stone" not in c.text for c in _chunks() if c.rule_id.startswith("R"))


def test_a_rule_merges_with_clauses_that_fit():
    # At the default size each rule here absorbs its clauses.
    ids = [c.rule_id for c in _chunks()]
    assert [i for i in ids if i.startswith("R")] == ["R1", "R2", "R3", "R4", "R5"]


def test_a_citation_of_a_clause_verifies_against_a_merged_rule():
    [r2] = [c for c in _chunks() if c.rule_id == "R2"]
    retrieved = [RetrievedChunk(text=r2.text, source="c.pdf", domain="curling", rule_id="R2",
                                page_start=2, page_end=2, distance=0.5)]
    assert find_unverified_citations("Removed [curling R2(b)].", retrieved) == []


def test_parent_id():
    assert _parent_id("14.2.7") == "14.2"
    assert _parent_id("R1(b)") == "R1"
    assert _parent_id("14") == ""
    assert _parent_id("CHAMPIONSHIPS (PCCC)") == ""
