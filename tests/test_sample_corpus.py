# Copyright (c) 2026 Eric Cooper.
"""The committed sample corpora chunk cleanly — no API, no built index needed.

These are the sample domains a fresh clone can build and ask against with zero
downloads (rules/checkers/, rules/tennis/, rules/poker/). This guard proves they stay
ingestable and that the section-aware chunker keeps finding their numbered
rules, so the tutorial's first step never silently rots into empty-index land.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rulebook.chunking import MIN_CHARS, chunk_pages
from rulebook.ingest import extract_pages

RULES_ROOT = Path(__file__).resolve().parents[1] / "rules"

# (domain, a few rule ids that must survive chunking)
SAMPLES = [
    ("checkers", {"1.1", "2.1", "3.3", "5.1"}),
    ("tennis", {"1.1", "3.4", "5.2", "5.4"}),
    ("poker", {"1.1", "3.2", "4.1", "5.4"}),
]


@pytest.mark.parametrize("domain, expected_ids", SAMPLES)
def test_sample_corpus_chunks_cleanly(domain: str, expected_ids: set[str]) -> None:
    doc = RULES_ROOT / domain / f"{domain}.md"
    assert doc.exists(), f"missing committed sample corpus {doc}"

    chunks = chunk_pages(extract_pages(doc), source=doc.name, domain=domain)
    ids = {c.rule_id for c in chunks}

    # The numbered rules were detected (not the per-page/markdown fallback).
    assert expected_ids <= ids, f"{domain}: missing {expected_ids - ids}"
    # Every chunk is this domain, non-trivial, and carries real text.
    assert chunks, f"{domain}: produced no chunks"
    assert all(c.domain == domain for c in chunks)
    assert all(len(c.text) >= MIN_CHARS for c in chunks)
    assert all(c.text.strip() for c in chunks)


def test_sample_domains_present() -> None:
    present = {p.name for p in RULES_ROOT.iterdir() if p.is_dir()}
    assert {"checkers", "tennis", "poker"} <= present
