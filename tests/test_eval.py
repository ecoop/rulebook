# Copyright (c) 2026 Eric Cooper.
"""The retrieval eval harness: the metrics are pure, and the gold set stays valid.

The hit@k / MRR math is tested on synthetic id lists (no index, no network). The
gold-validity test is the important guard: it re-chunks the committed sample
corpora and asserts every gold rule_id still exists — so a chunking change or a
rules edit that strands a gold label fails here instead of silently tanking the
scores. An optional integration test runs evaluate() against a locally built
index and is skipped when there isn't one (e.g. in CI).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rulebook.chunking import chunk_pages
from rulebook.eval import (
    evaluate,
    hit_at_k,
    load_gold,
    reciprocal_rank,
)
from rulebook.ingest import extract_pages

RULES_ROOT = Path(__file__).resolve().parents[1] / "rules"
DOMAINS = ["checkers", "cornhole", "poker"]


# --- pure metric functions (no index, no network) ---------------------------


def test_hit_at_k_respects_the_cutoff():
    assert hit_at_k(["a", "b", "c"], ("b",), k=2) is True
    assert hit_at_k(["a", "b", "c"], ("b",), k=1) is False  # b is rank 2, outside top-1
    assert hit_at_k(["a", "b"], ("x",), k=5) is False
    # any acceptable gold counts
    assert hit_at_k(["a", "b"], ("x", "b"), k=2) is True


def test_reciprocal_rank_is_one_over_first_hit():
    assert reciprocal_rank(["a", "b", "c"], ("b",)) == 0.5
    assert reciprocal_rank(["a", "b", "c"], ("a",)) == 1.0
    assert reciprocal_rank(["a", "b", "c"], ("x",)) == 0.0
    # the FIRST hit sets the rank, even if a later id also matches
    assert reciprocal_rank(["c", "a", "c"], ("a", "c")) == 1.0


# --- the committed gold set --------------------------------------------------


def test_load_gold_parses_both_domains():
    items = load_gold()
    assert {i.domain for i in items} >= set(DOMAINS)
    assert all(i.gold for i in items), "every gold item needs at least one rule_id"
    assert all(isinstance(i.gold, tuple) for i in items)


@pytest.mark.parametrize("domain", DOMAINS)
def test_gold_ids_exist_in_corpus(domain: str) -> None:
    doc = RULES_ROOT / domain / f"{domain}.md"
    ids = {c.rule_id for c in chunk_pages(extract_pages(doc), source=doc.name, domain=domain)}
    items = load_gold(domain)
    assert items, f"no gold for {domain}"
    for item in items:
        missing = set(item.gold) - ids
        assert not missing, f"{domain}: gold {missing} for {item.question!r} not a real rule_id"


# --- integration: run against a locally built index (skipped in CI) ----------


def test_evaluate_runs_against_a_built_index() -> None:
    pytest.importorskip("model2vec")
    from rulebook.config import settings
    from rulebook.store import list_domains

    if "checkers" not in set(list_domains(settings.resolved_index_path)):
        pytest.skip("no checkers index built (expected in CI); build it to run this")

    items = load_gold("checkers")
    res = evaluate(items, k=5)
    assert res.n == len(items)
    assert 0.0 <= res.hit_rate <= 1.0
    assert 0.0 <= res.mrr <= 1.0
    # by-style keys cover exactly the styles present in the gold set.
    assert set(res.by_style()) == {s or "(unlabeled)" for s in (i.style for i in items)}
