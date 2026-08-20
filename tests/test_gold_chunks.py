# Copyright (c) 2026 Eric Cooper.
"""Gold chunking (#133): cross-domain 'shared' text fans into covered domains."""

from __future__ import annotations

import json

import scripts.build_index as bi

KNOWN = {"ultimate", "goaltimate", "badminton"}


def test_split_gold_sections_separates_shared_from_domains():
    text = (
        "Both use a disc and start with a pull.\n"
        "## Ultimate\nStall count is ten.\n"
        "## Shared\nFiled under a non-domain heading.\n"
        "## Goaltimate\nUses a hoop."
    )
    domain_sections, shared = bi._split_gold_sections(text, KNOWN)
    assert domain_sections == [("ultimate", "Stall count is ten."),
                               ("goaltimate", "Uses a hoop.")]
    assert "Both use a disc" in shared            # the preamble
    assert "non-domain heading" in shared         # the ## Shared section


def test_split_gold_sections_no_headings():
    assert bi._split_gold_sections("just prose", KNOWN) == ([], "")


def _load(tmp_path, monkeypatch, *, fanout: bool):
    monkeypatch.setattr(bi, "read_latest_curation", lambda: {})
    monkeypatch.setattr(bi.settings, "gold_shared_fanout", fanout)
    gold = tmp_path / "gold.jsonl"
    gold.write_text(json.dumps({
        "gold_id": "g1",
        "gold_answer": "Both use a disc.\n## Ultimate\nStall is ten.\n## Goaltimate\nUses a hoop.",
    }) + "\n")
    chunks, records = bi.load_gold_chunks(gold, KNOWN)
    by: dict[str, list[str]] = {}
    for c in chunks:
        by.setdefault(c.domain, []).append(c.text)
    return by, records


def test_shared_fans_into_covered_domains(tmp_path, monkeypatch):
    by, records = _load(tmp_path, monkeypatch, fanout=True)
    # Each covered domain gets its specific chunk AND the shared preamble.
    assert any("Stall is ten" in t for t in by["ultimate"])
    assert any("Both use a disc" in t for t in by["ultimate"])
    assert any("Uses a hoop" in t for t in by["goaltimate"])
    assert any("Both use a disc" in t for t in by["goaltimate"])
    # A domain the gold does NOT cover gets nothing.
    assert "badminton" not in by
    assert records[0]["domains"] == ["goaltimate", "ultimate"]


def test_shared_dropped_when_fanout_off(tmp_path, monkeypatch):
    by, _ = _load(tmp_path, monkeypatch, fanout=False)
    assert any("Stall is ten" in t for t in by["ultimate"])
    assert not any("Both use a disc" in t for t in by["ultimate"])  # shared dropped
