# Copyright (c) 2026 Eric Cooper.
"""Tests for the answer-generation system prompt (grounding guardrails).

We can't cheaply assert model behavior, but we can assert the prompt carries
the constraints we rely on — in particular the guardrail that stops the model
from answering for / citing a domain that isn't in the retrieved context (a
goaltimate answer for a user without goaltimate, or a poker answer at all).
"""

from __future__ import annotations

from rulebook.generate import build_system_prompt, find_unverified_citations
from rulebook.retrieve import RetrievedChunk


def _chunk(domain: str, rule_id: str) -> RetrievedChunk:
    return RetrievedChunk(
        text="…", source="s.pdf", domain=domain, rule_id=rule_id,
        page_start=0, page_end=0, distance=0.1,
    )


def test_prompt_names_the_domains_in_play():
    p = build_system_prompt(["ultimate", "hearts"])
    assert "ultimate" in p and "hearts" in p


def test_prompt_refuses_domains_absent_from_context():
    # Guardrail against citation hallucination: the model must not answer for or
    # cite a domain with no excerpt in the context. See #172 for the structural
    # (post-hoc citation-validation) complement.
    low = build_system_prompt(["ultimate", "hearts"]).lower()
    assert "only the rule sets named above are available" in low
    assert "aren't in the provided context" in low
    # It must still force the inline citation format.
    assert "[domain rule_id]" in low


def test_prompt_allows_relaying_in_context_mentions_of_other_games():
    # Finer line: fabricating rules for an absent game is forbidden, but if an
    # available rule set's own excerpt mentions another game (e.g. Hearts noting
    # it's a trick-taking game like Bridge), relaying that — cited to the
    # available domain — is fair game. Guard against over-blocking that.
    low = build_system_prompt(["hearts"]).lower()
    assert "may still relay" in low
    assert "cited to the available domain" in low


def test_prompt_falls_back_when_no_domains():
    assert "the provided rules" in build_system_prompt([])


# --- find_unverified_citations (#172) -------------------------------------

_CHUNKS = [
    _chunk("ultimate", "II.B.1"),
    _chunk("hearts", "Object of the Game"),
]


def test_all_citations_verified_returns_empty():
    answer = "Seven per team [ultimate II.B.1]. Avoid points [hearts Object of the Game]."
    assert find_unverified_citations(answer, _CHUNKS) == []


def test_flags_real_domain_not_retrieved():
    # goaltimate is a real domain, but no goaltimate chunk was retrieved.
    answer = "Make it, take it [goaltimate XII.A.2/B]."
    assert find_unverified_citations(answer, _CHUNKS) == ["goaltimate XII.A.2/B"]


def test_flags_entirely_fabricated_domain():
    # poker isn't a domain at all — still caught.
    answer = "Deal five cards [poker 1.2]."
    assert find_unverified_citations(answer, _CHUNKS) == ["poker 1.2"]


def test_ignores_markdown_links():
    answer = "See the [official rules](https://example.com/rules) for details."
    assert find_unverified_citations(answer, _CHUNKS) == []


def test_multiword_rule_id_matches():
    answer = "The aim is stated in [hearts Object of the Game]."
    assert find_unverified_citations(answer, _CHUNKS) == []


def test_tolerates_page_suffix_from_header():
    # Model copied the context header's page suffix; still counts as verified.
    answer = "Seven per team [ultimate II.B.1 — pp.3-4]."
    assert find_unverified_citations(answer, _CHUNKS) == []


def test_dedupes_repeated_bogus_citation():
    answer = "[goaltimate X.A] … again [goaltimate X.A]."
    assert find_unverified_citations(answer, _CHUNKS) == ["goaltimate X.A"]
