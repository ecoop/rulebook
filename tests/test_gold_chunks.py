# Copyright (c) 2026 Eric Cooper.
"""Gold chunking (#133): cross-domain 'shared' text fans into covered domains."""

from __future__ import annotations

import json

import scripts.build_index as bi
from rulebook.gold_domains import (
    gold_target_domains,
    qa_domains,
    resolve_domains,
)

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


# --- domain attribution (#135) -------------------------------------------------


def test_qa_domains_frozen_list_single_or_null():
    assert qa_domains({"domains": ["ultimate", "goaltimate"]}) == ["ultimate", "goaltimate"]
    assert qa_domains({"domain": "ultimate"}) == ["ultimate"]
    assert qa_domains({"domain": None}) is None   # old cross/"all" — ambiguous
    assert qa_domains({}) is None


def test_resolve_domains_precedence_and_known_filter():
    known = {"ultimate", "goaltimate"}
    # explicit ▸ qa ▸ legacy
    assert resolve_domains(explicit=["ultimate"], qa=["goaltimate"], legacy=["goaltimate"], known=known) == ["ultimate"]
    # a chosen domain that no longer exists drops → legacy
    assert resolve_domains(explicit=None, qa=["badminton"], legacy=["ultimate"], known=known) == ["ultimate"]
    # nothing explicit/qa → legacy, never all-known
    assert resolve_domains(explicit=None, qa=None, legacy=["ultimate", "goaltimate"], known=known) == ["ultimate", "goaltimate"]


def test_gold_target_domains_headings_beat_qa():
    g = {"gold_answer": "## Ultimate\nfoo", "qa_id": "qa1"}
    got = gold_target_domains(g, {"qa1": {"domains": ["badminton"]}}, legacy=["goaltimate"], known=KNOWN)
    assert got == ["ultimate"]  # its ## heading wins over the qa row


def _load_headingless(tmp_path, monkeypatch, *, qa_rows, extra=None, attribution=True):
    monkeypatch.setattr(bi, "read_latest_curation", lambda: {})
    monkeypatch.setattr(bi, "read_qa_entries", lambda: qa_rows)
    monkeypatch.setattr(bi.settings, "gold_domain_attribution", attribution)
    monkeypatch.setattr(bi.settings, "gold_legacy_domains", ["ultimate", "goaltimate"])
    monkeypatch.setattr(bi.settings, "gold_shared_fanout", True)
    row = {"gold_id": "g1", "qa_id": "qa1", "question": "q", "gold_answer": "a heading-less answer."}
    if extra:
        row.update(extra)
    gold = tmp_path / "gold.jsonl"
    gold.write_text(json.dumps(row) + "\n")
    chunks, _ = bi.load_gold_chunks(gold, KNOWN)
    return {c.domain for c in chunks}


def test_headingless_attributes_to_qa_domains(tmp_path, monkeypatch):
    # qa question ran against ultimate only → gold indexes ONLY into ultimate.
    doms = _load_headingless(tmp_path, monkeypatch, qa_rows=[{"qa_id": "qa1", "domains": ["ultimate"]}])
    assert doms == {"ultimate"}


def test_headingless_persisted_domains_win(tmp_path, monkeypatch):
    doms = _load_headingless(
        tmp_path, monkeypatch,
        qa_rows=[{"qa_id": "qa1", "domains": ["ultimate"]}],
        extra={"domains": ["goaltimate"]},
    )
    assert doms == {"goaltimate"}  # explicit persisted overrides the qa row


def test_headingless_null_all_uses_legacy_not_everything(tmp_path, monkeypatch):
    # Old "all" (domain null, no frozen list) → legacy set, NOT badminton.
    doms = _load_headingless(tmp_path, monkeypatch, qa_rows=[{"qa_id": "qa1", "domain": None}])
    assert doms == {"ultimate", "goaltimate"}


def test_headingless_missing_qa_uses_legacy(tmp_path, monkeypatch):
    doms = _load_headingless(tmp_path, monkeypatch, qa_rows=[])
    assert doms == {"ultimate", "goaltimate"}


def test_attribution_off_restores_fan_to_all(tmp_path, monkeypatch):
    doms = _load_headingless(
        tmp_path, monkeypatch,
        qa_rows=[{"qa_id": "qa1", "domains": ["ultimate"]}],
        attribution=False,
    )
    assert doms == KNOWN  # pre-#135 behavior: every known domain
