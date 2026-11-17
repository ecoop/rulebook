# Copyright (c) 2026 Eric Cooper.
"""Definitions a retrieved passage depends on, added to the model's context.

A rule is often written in a rule set's own defined terms: curling's R2(f) says a
stone must come to rest beyond "the hog line at the playing end", and only the
glossary says the playing end is the end the stone is delivered *to*. Retrieval
finds the rule (it matches the question) but not the definition (it doesn't), so
the model answers in words it was never given the meaning of.

This module reads a rule set's definitions section ("3. Definitions", "III.
Definitions", "DEFINITIONS", "GLOSSARY OF TERMS") out of its built index, then,
for a question, picks the definitions of terms the retrieved passages use near
the question's own words, and returns them as extra passages. They are cited like
any other passage, and need no rebuild: the definitions come from the chunks the
index already stores.

Two entry shapes are read:

    3.A. Best perspective: The most complete view ...       (term, colon)
    Hog Line A line extending across the width of ...       (term, then a sentence)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .retrieve import RetrievedChunk
from .store import CHUNKS_FILE, domain_index_path

# A definitions section's heading, optionally numbered ("3. Definitions").
_HEADING = re.compile(
    r"(?:^|(?<=\s))(?:(?P<num>\d{1,2}|[IVXL]{1,5})\.\s+)?"
    r"(?P<head>DEFINITIONS|Definitions|GLOSSARY OF TERMS|Glossary of Terms|GLOSSARY|Glossary)"
    r"(?=\s|$)"
)

# "3.A. Best perspective: ...", "A. Cleared Disc: ...", "3.Q.1. Captain: ..."
_COLON_ENTRY = re.compile(
    r"(?:^|(?<=\s))(?:\d{1,2}\.)?(?:[A-Z]|\d{1,2})(?:\.\d{1,2})*\.\s+(?P<term>[A-Z][^:.]{0,40}?):\s"
)

# "Hog Line A line ...": a capitalised term after a sentence end, then a sentence
# that opens the way definitions do.
_OPENERS = (
    "A|An|The|In|Any|When|Each|Two|One|This|Used|Material|Slippery|See|Also|At"
)
_TERM = r"[A-Z][\w’'/-]*(?:\s+(?:[A-Z(][\w’'()/.-]*|[a-z][\w’'-]*|/)){0,5}?"
_SENTENCE_ENTRY = re.compile(
    rf"(?:^|(?<=[.)]\s))(?P<term>{_TERM})\s+(?=(?:{_OPENERS})\s)"
)

# Too few entries means the heading wasn't really a definitions section.
_MIN_ENTRIES = 3


@dataclass(frozen=True)
class Definition:
    term: str
    text: str           # the definition, without the term
    domain: str
    source: str
    rule_id: str        # the stored passage the definition sits in
    page_start: int
    page_end: int

    def as_chunk(self) -> RetrievedChunk:
        return RetrievedChunk(
            text=f"{self.term}: {self.text}",
            source=self.source,
            domain=self.domain,
            rule_id=self.rule_id,
            page_start=self.page_start,
            page_end=self.page_end,
            distance=None,
            defines=self.term,
        )


def extract_definitions(rows: list[dict]) -> list[Definition]:
    """The defined terms in one rule set's stored passages, in document order."""
    out: list[Definition] = []
    by_source: dict[str, list[dict]] = {}
    for row in sorted(rows, key=lambda r: r.get("ordinal", 0)):
        by_source.setdefault(row["source"], []).append(row)
    for source_rows in by_source.values():
        out.extend(_from_source(source_rows))
    return out


def _from_source(rows: list[dict]) -> list[Definition]:
    for i, row in enumerate(rows):
        text = " ".join(row["text"].split())
        for m in _HEADING.finditer(text):
            # The section: the rest of this passage, then the passages filed under
            # the heading's number ("3", "3.A", ...) or, unnumbered, its rule id.
            num = m.group("num")
            if num:
                belongs = lambda rid, n=num: rid == n or rid.startswith(n + ".")  # noqa: E731
            else:
                belongs = lambda rid, h=row["rule_id"]: rid == h  # noqa: E731
            parts = [(row, text[m.end():])]
            for later in rows[i + 1:]:
                if not belongs(later["rule_id"]):
                    break
                parts.append((later, " ".join(later["text"].split())))
            found = _parse(parts)
            if len(found) >= _MIN_ENTRIES:
                return found
    return []


def _parse(parts: list[tuple[dict, str]]) -> list[Definition]:
    """Split a section's text into entries, each tied to the passage it starts in."""
    joined, starts = "", []
    for row, text in parts:
        if text := text.strip():
            starts.append((len(joined), row))
            joined += text + " "
    joined = joined.rstrip()

    matches = list(_COLON_ENTRY.finditer(joined))
    if len(matches) < _MIN_ENTRIES:
        matches = list(_SENTENCE_ENTRY.finditer(joined))

    out = []
    for n, m in enumerate(matches):
        end = matches[n + 1].start() if n + 1 < len(matches) else len(joined)
        body = _opening(joined[m.end():end])
        if not body:
            continue
        row = next(r for p, r in reversed(starts) if p <= m.start())
        out.append(Definition(
            term=m.group("term").strip(),
            text=body,
            domain=row["domain"],
            source=row["source"],
            rule_id=row["rule_id"],
            page_start=int(row["page_start"]),
            page_end=int(row["page_end"]),
        ))
    return out


# A sentence ends at a full stop before a capital or a digit, so "13 mm. (1/2 in.)"
# stays one sentence.
_SENTENCE = re.compile(r"(?<=[.;])\s+(?=[A-Z0-9“\"‘'])")
# A numbered item ("3.A.2.", "1.", "R.") starts a sub-rule, not more definition.
_ITEM = re.compile(r"(?:\d{1,2}\.|[A-Z]\.)(?:[A-Z0-9]{1,2}\.)*\s")
# What a definition keeps: its opening sentences, up to this many characters.
_DEFINITION_KEEP = 400


def _opening(body: str) -> str:
    """The definition proper: its first sentences, stopping at a sub-rule.

    Ultimate's "Possession of the disc" runs on into "3.I.1. Catching ..." and
    "Best perspective" into its video-review rule; the first sentence or two is
    the definition, and keeping only that keeps a linked definition small.
    """
    kept: list[str] = []
    for sentence in _SENTENCE.split(body.strip()):
        if _ITEM.match(sentence) or (kept and len(" ".join(kept + [sentence])) > _DEFINITION_KEEP):
            break
        kept.append(sentence)
        if len(kept) == 2:
            break
    return " ".join(kept)


# ---------------------------------------------------------------------------
# Choosing definitions for a question

# Room for the added definitions, in characters (~4 per token): a few curling
# terms or two of ultimate's longer ones.
DEFINITION_CHARS = 1600
MAX_DEFINITIONS = 6

_STOPWORDS = frozenset(
    "a an and are as at be by can do does for from how if in into is it its of on "
    "or that the their them then there these they this to was what when where which "
    "who why will with you your".split()
)
_WORD = re.compile(r"[a-z][a-z’'-]+")


def _forms(term: str) -> list[str]:
    """The ways a term appears in prose: as written, without its "(FGZ)", the
    abbreviation alone."""
    base = re.sub(r"\s*\([^)]*\)", "", term).strip()
    forms = [base]
    if abbr := re.search(r"\(([A-Z]{2,})\)", term):
        forms.append(abbr.group(1))
    return forms


def _pattern(term: str) -> re.Pattern:
    alts = "|".join(re.escape(f) for f in _forms(term))
    return re.compile(rf"\b(?:{alts})(?:s|es)?\b", re.IGNORECASE)


# How close (in characters, about a dozen words) a question word must be to a
# term's use for the term to count as part of the answer's vocabulary.
_NEAR_CHARS = 70


def _used_near(pat: re.Pattern, sentence: str, words: set[str]) -> bool:
    """True if ``sentence`` uses the term within _NEAR_CHARS of one of ``words``."""
    for m in pat.finditer(sentence):
        around = (
            sentence[max(0, m.start() - _NEAR_CHARS):m.start()]
            + " " + sentence[m.end():m.end() + _NEAR_CHARS]
        )
        if words & set(_WORD.findall(around.lower())):
            return True
    return False


def choose_definitions(
    question: str,
    chunks: list[RetrievedChunk],
    definitions: list[Definition],
    *,
    budget: int = DEFINITION_CHARS,
    limit: int = MAX_DEFINITIONS,
) -> list[Definition]:
    """The definitions worth adding for ``question``, best first.

    A term qualifies when the question uses it, or a retrieved passage uses it in
    a sentence that also has one of the question's words: "the hog line at the
    playing end" earns *Playing End* for a hog-line question; the centre line,
    named in the same passage but not near the hog line, does not. A one-word term
    ("End", "Player") is plain English often enough that it counts only when the
    question itself uses it. Definitions already inside a retrieved passage are
    skipped. Ranked by those counts, then added until ``budget`` characters or
    ``limit`` definitions.
    """
    keywords = {w for w in _WORD.findall(question.lower()) if w not in _STOPWORDS}
    sentences = [
        (rank, s) for rank, c in enumerate(chunks) for s in _SENTENCE.split(c.text)
    ]
    context = " ".join(c.text for c in chunks)
    scored = []
    for d in definitions:
        if d.text[:60] in context:
            continue
        pat = _pattern(d.term)
        in_question = bool(pat.search(question))
        if not in_question and len(_forms(d.term)[0].split()) < 2:
            continue
        # The term's own words don't count: "line" in a hog-line question would
        # otherwise pull in every *Line the passages mention.
        near = keywords - set(_WORD.findall(d.term.lower()))
        hits = [rank for rank, s in sentences if _used_near(pat, s, near)]
        if in_question or hits:
            scored.append((-(10 * in_question + len(hits)), min(hits, default=0), d))
    scored.sort(key=lambda t: (t[0], t[1]))
    # "offensive player" in the question names Offensive player, not Player too.
    named = [d.term.lower() for s, _, d in scored if s <= -10]
    scored = [
        t for t in scored
        if not any(t[2].term.lower() != n and t[2].term.lower() in n for n in named)
    ]

    out, used = [], 0
    for _, _, d in scored:
        size = len(d.term) + len(d.text) + 2
        if used + size > budget or len(out) >= limit:
            continue
        out.append(d)
        used += size
    return out


# ---------------------------------------------------------------------------
# Loading, cached per index file

_cache: dict[Path, tuple[int, list[Definition]]] = {}


def definitions_for(index_root: Path, domain: str) -> list[Definition]:
    """``domain``'s definitions, re-read only when its chunks file changes."""
    path = domain_index_path(index_root, domain) / CHUNKS_FILE
    try:
        stamp = path.stat().st_mtime_ns
    except FileNotFoundError:
        return []
    cached = _cache.get(path)
    if cached and cached[0] == stamp:
        return cached[1]
    with path.open() as f:
        rows = [json.loads(line) for line in f]
    for r in rows:  # pre-rename indexes key rows on "sport" (see store.Store.load)
        r.setdefault("domain", r.get("sport", domain))
    found = extract_definitions(rows)
    _cache[path] = (stamp, found)
    return found


def link_definitions(
    question: str, chunks: list[RetrievedChunk], index_root: Path
) -> list[RetrievedChunk]:
    """Passages defining the terms ``chunks`` lean on, for each domain in them."""
    out: list[RetrievedChunk] = []
    for domain in dict.fromkeys(c.domain for c in chunks):
        mine = [c for c in chunks if c.domain == domain]
        chosen = choose_definitions(question, mine, definitions_for(index_root, domain))
        out.extend(d.as_chunk() for d in chosen)
    return out
