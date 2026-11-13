# Copyright (c) 2026 Eric Cooper.
"""The answers RAG at a glance shows (saved, so it needs no key) still match the sample rules.

If a sample rule is renumbered or removed, a saved answer would cite a rule that no
longer exists. This catches that, without a key or a built index: every citation
must name a rule the sample's own chunker produces. Re-record with
scripts/record_glance_answers.py.
"""

from __future__ import annotations

import json
from pathlib import Path

from rulebook.chunking import chunk_pages
from rulebook.generate import find_unverified_citations
from rulebook.ingest import extract_pages
from rulebook.retrieve import RetrievedChunk

ROOT = Path(__file__).resolve().parents[1]
SAVED = json.loads((ROOT / "notebooks" / "data" / "rag_at_a_glance_answers.json").read_text())


def _all_rules(domain: str) -> list[RetrievedChunk]:
    doc = ROOT / "rules" / domain / f"{domain}.md"
    return [
        RetrievedChunk(text=c.text, source=c.source, domain=c.domain, rule_id=c.rule_id,
                       page_start=0, page_end=0, distance=0.0)
        for c in chunk_pages(extract_pages(doc), source=doc.name, domain=domain)
    ]


def test_saved_answers_cite_only_rules_that_exist() -> None:
    assert len(SAVED["answers"]) == 3
    for entry in SAVED["answers"]:
        domains = entry.get("domains") or [entry["domain"]]
        rules = [c for d in domains for c in _all_rules(d)]
        assert entry["answer"].strip(), entry["question"]
        assert find_unverified_citations(entry["answer"], rules) == [], entry["question"]
