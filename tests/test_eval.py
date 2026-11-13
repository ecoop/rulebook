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
    EvalResult,
    GoldItem,
    ItemResult,
    build_scratch_index,
    citation_rule_id,
    evaluate,
    hit_at_k,
    load_gold,
    rank_of,
    reciprocal_rank,
)
from rulebook.ingest import extract_pages

RULES_ROOT = Path(__file__).resolve().parents[1] / "rules"
DOMAINS = ["checkers", "tennis", "poker"]


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
    assert all(i.citations for i in items), "every citation gold needs at least one citation"
    assert all(isinstance(i.citations, tuple) for i in items)
    # citations are domain-qualified, the same form answers cite them in
    assert all(c.startswith(f"{i.domain} ") for i in items for c in i.citations)


def test_citation_rule_id_parses_and_checks_the_domain():
    assert citation_rule_id("checkers 5.1", "checkers") == "5.1"
    assert citation_rule_id("ultimate II.B.1", "ultimate") == "II.B.1"
    assert citation_rule_id("5.1", "checkers") == "5.1"  # bare id: already this domain
    with pytest.raises(ValueError):
        citation_rule_id("tennis 1.1", "checkers")


def test_load_gold_reads_citations_and_the_legacy_gold_key(tmp_path):
    (tmp_path / "x.jsonl").write_text(
        '{"domain": "checkers", "question": "new", "citations": ["checkers 5.1"]}\n'
        '{"domain": "checkers", "question": "old", "gold": ["5.1", "2.1"]}\n'
    )
    new, old = load_gold(directory=tmp_path)
    assert new.citations == ("checkers 5.1",) and new.rule_ids == ("5.1",)
    assert old.citations == ("checkers 5.1", "checkers 2.1")
    assert old.rule_ids == ("5.1", "2.1")


def test_load_gold_rejects_a_citation_into_another_domain(tmp_path):
    (tmp_path / "x.jsonl").write_text(
        '{"domain": "checkers", "question": "q", "citations": ["tennis 1.1"]}\n'
    )
    with pytest.raises(ValueError):
        load_gold(directory=tmp_path)


@pytest.mark.parametrize("domain", DOMAINS)
def test_gold_ids_exist_in_corpus(domain: str) -> None:
    doc = RULES_ROOT / domain / f"{domain}.md"
    ids = {c.rule_id for c in chunk_pages(extract_pages(doc), source=doc.name, domain=domain)}
    items = load_gold(domain)
    assert items, f"no gold for {domain}"
    for item in items:
        missing = set(item.rule_ids) - ids
        assert not missing, f"{domain}: cited {missing} for {item.question!r} not a real rule_id"


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


def test_hit_rate_at_scores_any_k_up_to_the_retrieved_k():
    item = GoldItem("checkers", "q", ("b",))
    res = EvalResult(k=3, items=[ItemResult(item, ["a", "b", "c"], True, 0.5)])
    assert res.hit_rate_at(1) == 0.0  # b is rank 2
    assert res.hit_rate_at(2) == 1.0
    with pytest.raises(ValueError):
        res.hit_rate_at(4)  # only the top 3 were retrieved


# --- scratch index: compare a local model without touching data/index -------


def test_scratch_index_scores_without_touching_the_real_index(monkeypatch, tmp_path):
    pytest.importorskip("model2vec")
    from rulebook.config import settings

    # Point the real index at an empty dir; the scratch build must not write there.
    monkeypatch.setattr(settings, "index_path", tmp_path)
    model = "minishlab/potion-retrieval-32M"  # same model test_local_embedder caches
    try:
        idx = build_scratch_index("checkers", model)
    except Exception as e:  # noqa: BLE001 — model fetch failed (offline/rate-limited)
        pytest.skip(f"local model {model!r} unavailable: {e}")
    assert not any(tmp_path.iterdir()), "scratch build wrote into the real index"

    items = load_gold("checkers")
    res = evaluate(items, k=5, index=idx)
    assert res.n == len(items)
    assert 0.0 <= res.hit_rate_at(1) <= res.hit_rate_at(3) <= res.hit_rate_at(5)
    assert res.hit_rate_at(5) == res.hit_rate

    r = rank_of(items[0].question, items[0].citations, index=idx)
    assert r is None or 1 <= r <= 5
    with pytest.raises(ValueError):
        rank_of("q", ("1.1",), domain="tennis", index=idx)  # wrong domain for this index


def test_hits_at_counts_and_hit_cell_shows_both():
    from rulebook.notebook import hit_cell

    a, b = GoldItem("checkers", "q1", ("x",)), GoldItem("checkers", "q2", ("y",))
    res = EvalResult(
        k=3,
        items=[ItemResult(a, ["x", "p", "q"], True, 1.0), ItemResult(b, ["p", "q", "y"], True, 1 / 3)],
    )
    assert (res.hits_at(1), res.hits_at(3)) == (1, 2)
    assert res.hit_rate_at(1) == 0.5
    assert hit_cell(res, 1) == "0.50 (1/2)"
    many = EvalResult(k=1, items=[ItemResult(a, ["p"], False, 0.0)] * 12)
    assert hit_cell(many, 1) == "0.00 (\u20070/12)"  # padded to line up with "(10/12)"
    assert EvalResult(k=5).hit_rate_at(1) == 0.0  # empty result, no division by zero
