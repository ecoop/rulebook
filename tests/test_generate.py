# Copyright (c) 2026 Eric Cooper.
"""Tests for the answer-generation system prompt (grounding guardrails).

We can't cheaply assert model behavior, but we can assert the prompt carries
the constraints we rely on — in particular the guardrail that stops the model
from answering for / citing a domain that isn't in the retrieved context (a
goaltimate answer for a user without goaltimate, or a poker answer at all).
"""

from __future__ import annotations

from rulebook.generate import build_system_prompt


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
