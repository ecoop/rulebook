# Copyright (c) 2026 Eric Cooper.
"""A rule absorbs its sub-rules, so a list's lead-in stays with its items."""

from __future__ import annotations

from pathlib import Path

import pytest

from rulebook.chunking import MERGE_CHARS, _merge_into_parents, chunk_pages
from rulebook.config import Settings
from rulebook.generate import find_unverified_citations
from rulebook.ingest import PageText, extract_pages
from rulebook.retrieve import RetrievedChunk

REPO = Path(__file__).resolve().parents[1]

# A lead-in under MIN_CHARS, then a list whose items never name the rule.
LETS = """3.1 Lets. It shall be a let if:
3.1.1 the server serves before the receiver is ready;
3.1.2 both players are faulted at once;
3.1.3 an accident occurs.
3.2 Faults are called by the umpire whenever one of the listed conditions occurs during play.
3.3 Play shall be continuous from the first service until the end of the match, with no breaks.
"""


def _chunks(text: str, **kw):
    return chunk_pages([PageText(page_number=1, text=text)], source="t.md", domain="t", **kw)


def _anchors(text: str, ids: list[str]) -> list[tuple[int, str]]:
    """(offset, id) for each id, found at the start of its line."""
    return [(text.index(f"{i} "), i) for i in ids]


def test_lead_in_and_list_become_one_chunk():
    chunks = _chunks(LETS)
    assert [c.rule_id for c in chunks] == ["3.1", "3.2", "3.3"]
    lets = chunks[0].text
    assert lets.startswith("3.1 Lets. It shall be a let if:")
    assert "3.1.3 an accident occurs." in lets


def test_without_merging_the_lead_in_and_items_are_lost():
    # Each piece is under MIN_CHARS, so one chunk per number keeps none of them.
    assert [c.rule_id for c in _chunks(LETS, merge_chars=0)] == ["3.2", "3.3"]


def test_a_sub_rule_of_a_merged_chunk_still_verifies():
    [lets] = [c for c in _chunks(LETS) if c.rule_id == "3.1"]
    retrieved = [RetrievedChunk(text=lets.text, source="t.md", domain="t", rule_id="3.1",
                                page_start=1, page_end=1, distance=0.5)]
    assert find_unverified_citations("Yes [t 3.1.2].", retrieved) == []


def test_a_parent_stops_absorbing_at_merge_chars():
    text = "".join(f"{i} {'Word ' * 6}\n" for i in ["1", "1.1", "1.2", "1.3", "1.4"])
    anchors = _anchors(text, ["1", "1.1", "1.2", "1.3", "1.4"])
    # Each rule is ~35 characters: three fit in 110. 1.3 then starts a chunk, and
    # 1.4 isn't under it (nor a list item continuing it), so it starts its own.
    assert [rid for _, rid in _merge_into_parents(text, anchors, 110)] == ["1", "1.3", "1.4"]


def test_list_items_without_a_detected_parent_merge_under_the_parent_id():
    text = ("13.3.6 is caught and slung during a stroke;\n"
            "13.3.7 is hit twice in succession by one player; or\n"
            "13.3.8 is hit by a player and then the partner.\n"
            "13.4.1 touches the net with racket or person;\n")
    anchors = _anchors(text, ["13.3.6", "13.3.7", "13.3.8", "13.4.1"])
    merged = _merge_into_parents(text, anchors, 1000)
    assert [rid for _, rid in merged] == ["13.3", "13.4.1"]
    assert merged[0][0] == anchors[0][0]


def test_self_contained_siblings_stay_apart():
    # Definitions start uppercase: each is a rule of its own, not a list item.
    text = ("3.B Foul: contact between opposing players.\n"
            "3.C Ground contact: any contact with the ground.\n"
            "3.D Guarding: a defender within ten feet.\n")
    anchors = _anchors(text, ["3.B", "3.C", "3.D"])
    assert _merge_into_parents(text, anchors, 1000) == anchors


@pytest.mark.parametrize("domain", ["checkers", "poker", "tennis"])
def test_sample_rule_sets_are_unchanged(domain):
    # Numbered one level deep (4.1, 4.2 …), so nothing merges: the sample indexes,
    # gold sets and notebook numbers stay as they were.
    for doc in sorted((REPO / "rules" / domain).glob("*.md")):
        pages = extract_pages(doc)
        merged = chunk_pages(pages, source=doc.name, domain=domain)
        unmerged = chunk_pages(pages, source=doc.name, domain=domain, merge_chars=0)
        assert [(c.rule_id, c.text) for c in merged] == [(c.rule_id, c.text) for c in unmerged]


def test_setting_default_matches_the_chunker():
    assert Settings.model_fields["chunk_merge_chars"].default == MERGE_CHARS
