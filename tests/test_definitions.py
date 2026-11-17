# Copyright (c) 2026 Eric Cooper.
"""Definitions sections are read from an index and linked to the passages that use them."""

from __future__ import annotations

import json

from rulebook import pipeline
from rulebook.config import settings
from rulebook.definitions import (
    Definition,
    choose_definitions,
    extract_definitions,
    link_definitions,
)
from rulebook.generate import GeneratedAnswer, find_unverified_citations
from rulebook.retrieve import RetrievedChunk


def _row(rule_id, text, n, source="r.pdf", domain="curling", page=9):
    return {"source": source, "domain": domain, "rule_id": rule_id, "page_start": page,
            "page_end": page, "text": text, "ordinal": n}


GLOSSARY = [
    _row("R2(f)", "(f) A stone that does not come to rest beyond the hog line at the playing "
         "end is removed from play.", 0, page=7),
    _row("GLOSSARY OF TERMS", "GLOSSARY OF TERMS Centre Line The line dividing the playing "
         "surface down the middle. Delivery End The end of the sheet from which the stones are "
         "being delivered. End A portion of a game. Hog Line A line across the sheet, parallel "
         "to each tee line.", 1, page=65),
    _row("GLOSSARY OF TERMS", "Playing End The end of the sheet to which the stones are being "
         "delivered. Rock See definition: Stone. Stone Also known as a rock.", 2, page=66),
]

ULTIMATE = [
    _row("3", "3. Definitions .......................... 4", 0, domain="ultimate"),
    _row("2.H", "2.H. Experienced players explain the rules. 3. Definitions", 1, domain="ultimate"),
    _row("3.A", "3.A. Best perspective: The most complete view of a play. Best perspective "
         "always belongs to a player.", 2, domain="ultimate"),
    _row("3.A.2", "3.A.2. Players may review video footage. Play may not be delayed.", 3,
         domain="ultimate"),
    _row("3.B", "3.B. Foul: Non-Incidental contact between opposing players.", 4, domain="ultimate"),
    _row("3.Q", "3.Q. Roles 3.Q.1. Captain: A team member who represents the team.", 5,
         domain="ultimate"),
    _row("3.Q.2", "3.Q.2. Offensive player: A player whose team has the disc. 3.Q.3. Player: "
         "One of the persons in the game.", 6, domain="ultimate"),
    _row("4", "4. Field: Rectangular, with an end zone at each end.", 7, domain="ultimate"),
]


def _chunk(row, distance=0.5):
    return RetrievedChunk(text=row["text"], source=row["source"], domain=row["domain"],
                          rule_id=row["rule_id"], page_start=row["page_start"],
                          page_end=row["page_end"], distance=distance)


def test_a_glossary_of_terms_and_sentences():
    found = {d.term: d for d in extract_definitions(GLOSSARY)}
    assert list(found) == ["Centre Line", "Delivery End", "End", "Hog Line", "Playing End",
                           "Rock", "Stone"]
    assert found["Playing End"].text == "The end of the sheet to which the stones are being delivered."
    # Cited to the stored passage the entry sits in.
    assert (found["Playing End"].rule_id, found["Playing End"].page_start) == ("GLOSSARY OF TERMS", 66)
    assert found["Rock"].text == "See definition: Stone."


def test_numbered_definitions_with_colons():
    found = {d.term: d for d in extract_definitions(ULTIMATE)}
    # The table-of-contents line has no entries after it; the section starts at the
    # heading that ends 2.H and stops before rule 4.
    assert list(found) == ["Best perspective", "Foul", "Captain", "Offensive player", "Player"]
    assert [found[t].rule_id for t in found] == ["3.A", "3.B", "3.Q", "3.Q.2", "3.Q.2"]
    # A definition keeps its opening sentences, not the sub-rule after it.
    assert found["Best perspective"].text == (
        "The most complete view of a play. Best perspective always belongs to a player.")


def test_a_definitions_block_inside_a_preamble():
    rows = [_row("preamble", "LAWS OF BADMINTON DEFINITIONS Player Any person playing. Match "
                 "The basic contest. Serving side The side having the right to serve. Rally A "
                 "sequence of strokes.", 0, domain="badminton"),
            _row("1", "1. COURT The court is a rectangle.", 1, domain="badminton")]
    assert [d.term for d in extract_definitions(rows)] == ["Player", "Match", "Serving side", "Rally"]


def test_no_definitions_section():
    rows = [_row("1", "1. The dealer shuffles. Each player gets thirteen cards.", 0)]
    assert extract_definitions(rows) == []


def _defs():
    return extract_definitions(GLOSSARY)


def test_the_questions_term_and_one_used_next_to_its_words_are_chosen():
    chunks = [_chunk(GLOSSARY[0])]
    chosen = choose_definitions("what is the purpose of the hog line?", chunks, _defs())
    # Hog Line: the question names it. Playing End: R2(f) says "the hog line at
    # the playing end".
    assert [d.term for d in chosen] == ["Hog Line", "Playing End"]


def test_a_term_far_from_the_questions_words_is_not():
    far = _row("R1(b)", "(b) The centre line joins the midpoints of the tee lines and extends "
               "beyond them by a length of twelve feet, measured along the ice to the hack. "
               "The hog line is 21 ft. from the tee.", 0)
    chosen = choose_definitions("what is the hog line for?", [_chunk(far)], _defs())
    assert [d.term for d in chosen] == ["Hog Line"]       # not Centre Line


def test_a_one_word_term_needs_the_question_to_use_it():
    chunks = [_chunk(GLOSSARY[0])]
    assert "End" not in [d.term for d in choose_definitions("hog line?", chunks, _defs())]
    assert "End" in [d.term for d in choose_definitions("how long is an end?", chunks, _defs())]


def test_a_definition_already_retrieved_is_not_added_again():
    chunks = [_chunk(r) for r in GLOSSARY]
    assert choose_definitions("purpose of the hog line?", chunks, _defs()) == []


def test_the_longer_term_the_question_names_wins():
    defs = extract_definitions(ULTIMATE)
    chosen = choose_definitions("can an offensive player call a foul?", [], defs)
    assert [d.term for d in chosen] == ["Foul", "Offensive player"]      # not Player


def test_the_budget_and_the_limit():
    defs = [Definition(f"Term {i}", "x" * 400, "curling", "r.pdf", "G", 1, 1) for i in range(9)]
    question = " ".join(f"term {i}" for i in range(9))
    assert len(choose_definitions(question, [], defs)) == 3      # 3 × 408 chars ≤ 1600 < 4 × 408
    assert len(choose_definitions(question, [], defs, budget=10_000)) == 6


def _index(tmp_path, rows, domain="curling"):
    (tmp_path / domain).mkdir(parents=True)
    with (tmp_path / domain / "chunks.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return tmp_path


def test_linked_definitions_are_citable_passages(tmp_path):
    root = _index(tmp_path, GLOSSARY)
    retrieved = [_chunk(GLOSSARY[0])]
    hog, linked = link_definitions("what is the purpose of the hog line?", retrieved, root)
    assert (linked.defines, linked.distance) == ("Playing End", None)
    assert linked.text.startswith("Playing End: The end of the sheet to which")
    answer = "Beyond the far hog line [curling R2(f)], the playing end [curling GLOSSARY OF TERMS]."
    assert find_unverified_citations(answer, retrieved + [hog, linked]) == []


def test_a_domain_without_an_index_links_nothing(tmp_path):
    assert link_definitions("hog line?", [_chunk(GLOSSARY[0])], tmp_path) == []


def test_ask_adds_definitions_unless_turned_off(tmp_path, monkeypatch):
    root = _index(tmp_path, GLOSSARY)
    monkeypatch.setattr(settings, "index_path", root)
    monkeypatch.setattr(pipeline, "retrieve", lambda question, domain, k: [_chunk(GLOSSARY[0])])
    seen = []

    def fake_generate(question, chunks):
        seen.append([c.rule_id for c in chunks])
        return GeneratedAnswer(answer="ok", input_tokens=1, output_tokens=1, stop_reason="end_turn")

    monkeypatch.setattr(pipeline, "generate_answer", fake_generate)
    result = pipeline.ask("what is the purpose of the hog line?", domain="curling")
    assert seen[-1] == ["R2(f)", "GLOSSARY OF TERMS", "GLOSSARY OF TERMS"]
    assert [c["defines"] for c in result.as_dict()["chunks"]] == [None, "Hog Line", "Playing End"]

    monkeypatch.setattr(settings, "link_definitions", False)
    pipeline.ask("what is the purpose of the hog line?", domain="curling")
    assert seen[-1] == ["R2(f)"]
