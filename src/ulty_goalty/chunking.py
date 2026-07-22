"""Section-aware chunking for rulebooks.

The single biggest quality lever in RAG over structured documents. A naive
"every 500 chars" chunker would slice mid-clause and give the embedder
garbage to match against. Section-aware chunking honors the document's
own hierarchy so each chunk is a self-contained rule.

STRATEGY

    1. Concatenate the pages into one long string, tracking the char->page
       map so we can attach page numbers back to each chunk.

    2. Scan for lines that start with a rule-numbering pattern (e.g.
       "1.A.1.", "II.B.", "Rule 5.2"). Those are the CHUNK BOUNDARIES.

    3. Split the text at those boundaries. Each resulting chunk carries
       its rule id, page range, sport, and source PDF.

    4. If a section is longer than MAX_CHARS, split it further at
       paragraph breaks with a small overlap so context bleeds across the
       cut and no single chunk becomes needle-in-a-haystack.

TUNING

    We try multiple regex patterns and use the one that matches the most
    times (as long as it clears MIN_ANCHORS_TO_TRUST). That way a rulebook
    using "1.A.1" doesn't get mis-detected by a pattern designed for
    "Rule 5.2". If neither works we fall back to per-page chunks and log
    a warning — not great, but retrievable.
"""

import re
from bisect import bisect_right
from dataclasses import dataclass

from .ingest import PageText


@dataclass
class Chunk:
    source: str        # PDF filename
    sport: str         # "ultimate" | "goaltimate" | ...
    rule_id: str       # e.g. "II.B.1"; "preamble" for pre-first-rule text
    page_start: int    # 1-indexed page numbers
    page_end: int
    text: str
    ordinal: int = 0   # index within the sport, assigned after chunking


# FLAT patterns — the rule id and its full hierarchy live on one line.
# The Official Rules of Ultimate use "2.C.1." style, all anchors flat.
# Each regex captures the rule id in group 1.
RULE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "roman.letter.digit",
        re.compile(r"^\s*([IVXLC]+\.[A-Z](?:\.\d+(?:\.[a-z])?)?)\.\s", re.M),
    ),
    (
        "digit.letter.digit",
        re.compile(r"^\s*(\d+\.[A-Z](?:\.\d+(?:\.[a-z])?)?)\.\s", re.M),
    ),
    (
        # Ultimate rulebook appendices: "B3.A.1.", "C1.D.3.b.", "D1."
        # Letter-digit prefix (Appendix section) then optional deeper path.
        "appendix.letter-digit",
        re.compile(r"^\s*([A-Z]\d+(?:\.[A-Z](?:\d+)?(?:\.\d+(?:\.[a-z])?)?)?)\.\s", re.M),
    ),
    (
        "rule.digits",
        re.compile(r"^\s*Rule\s+(\d+(?:\.\d+){1,3})\b", re.M | re.I),
    ),
    (
        "dotted.digits",
        re.compile(r"^\s*(\d+\.\d+(?:\.\d+){0,2})\.?\s", re.M),
    ),
]
MIN_ANCHORS_TO_TRUST = 5

# HIERARCHICAL patterns — each level appears alone at line start on its own
# line, and we synthesize a qualified rule id (e.g. "III.D.2") by tracking
# the most recent anchor at each level. This is what the USAG Goaltimate
# rulebook uses:
#
#     I.  Introduction            <- top-level (Roman)
#     A.  Description...          <- subsection (capital letter)
#     1.  Some sub-clause         <- leaf (digit)
#
# The lookahead requires an uppercase letter (roman/letter) or any letter
# (digit) after the whitespace, which weeds out the frequent list numbering
# inside prose that happens to sit at a line start.
_HIER_LEVELS = [
    (0, re.compile(r"^\s*([IVXLC]{1,4})\.\s+(?=[A-Z])", re.M)),   # I. II. III.
    (1, re.compile(r"^\s*([A-Z])\.\s+(?=[A-Za-z])", re.M)),        # A. B. C.
    (2, re.compile(r"^\s*(\d{1,3})\.\s+(?=[A-Za-z])", re.M)),      # 1. 2. 3.
]

MAX_CHARS = 1500       # ~350 tokens; comfortably under any embedder's cap
MIN_CHARS = 60         # discard shorter fragments (headings-only, page numbers)
SPLIT_OVERLAP = 150    # overlap between hard-cut pieces of an oversize section


def chunk_pages(pages: list[PageText], *, source: str, sport: str) -> list[Chunk]:
    """Chunk a list of PageText into a list of Chunk records."""
    if not pages:
        return []

    joined, page_starts = _join_with_offsets(pages)
    anchors = _detect_anchors(joined)

    if not anchors:
        # No rule-numbering detected — degrade gracefully to per-page chunks.
        return _fallback_per_page(pages, source=source, sport=sport)

    chunks: list[Chunk] = []

    # Optionally emit a "preamble" chunk for pre-first-anchor text.
    if anchors[0][0] > 0:
        preamble = joined[: anchors[0][0]].strip()
        if len(preamble) >= MIN_CHARS:
            page_end = _page_for(anchors[0][0] - 1, page_starts)
            for piece in _split_if_long(preamble):
                chunks.append(
                    Chunk(
                        source=source,
                        sport=sport,
                        rule_id="preamble",
                        page_start=1,
                        page_end=page_end,
                        text=piece,
                    )
                )

    # One chunk (or several, after _split_if_long) per anchor.
    for i, (offset, rule_id) in enumerate(anchors):
        end = anchors[i + 1][0] if i + 1 < len(anchors) else len(joined)
        section_text = joined[offset:end].strip()
        page_start = _page_for(offset, page_starts)
        page_end = _page_for(max(end - 1, offset), page_starts)
        for piece in _split_if_long(section_text):
            chunks.append(
                Chunk(
                    source=source,
                    sport=sport,
                    rule_id=rule_id,
                    page_start=page_start,
                    page_end=page_end,
                    text=piece,
                )
            )

    for i, c in enumerate(chunks):
        c.ordinal = i

    return [c for c in chunks if len(c.text) >= MIN_CHARS]


# --- helpers ---------------------------------------------------------------


def _join_with_offsets(pages: list[PageText]) -> tuple[str, list[int]]:
    """Return (concatenated_text, page_start_offsets).

    page_start_offsets[i] is the char offset in the concatenated string
    where page (i + 1) begins. We use bisect_right on this list to map any
    char offset back to a page number.
    """
    parts: list[str] = []
    starts: list[int] = []
    cursor = 0
    for p in pages:
        starts.append(cursor)
        block = p.text + "\n\n"
        parts.append(block)
        cursor += len(block)
    return "".join(parts), starts


def _page_for(char_offset: int, page_starts: list[int]) -> int:
    # bisect_right returns the number of pages whose start offset is <= char_offset,
    # which is exactly the 1-indexed page number.
    return max(1, bisect_right(page_starts, char_offset))


def _detect_anchors(text: str) -> list[tuple[int, str]]:
    """Combine anchors from every strategy that clears MIN_ANCHORS_TO_TRUST.

    Real rulebooks often mix numbering schemes — the Official Rules of
    Ultimate uses "2.C.1." for the main body AND "B3.A.1." for the
    appendices. If we pick one winning strategy the other's sections
    become one giant chunk. Instead we take matches from every strategy
    that "works", then dedupe by offset (longest rule id wins ties, since
    more specific = better citation).

    Threshold semantics: MIN_ANCHORS_TO_TRUST filters strategies that
    only made a handful of accidental matches. A rulebook's real
    numbering scheme will always match many more.
    """
    all_matches: list[tuple[int, str]] = []
    for _name, pattern in RULE_PATTERNS:
        matches = [(m.start(), m.group(1)) for m in pattern.finditer(text)]
        if len(matches) >= MIN_ANCHORS_TO_TRUST:
            all_matches.extend(matches)

    hierarchical = _detect_hierarchical_anchors(text)
    if len(hierarchical) >= MIN_ANCHORS_TO_TRUST:
        all_matches.extend(hierarchical)

    if not all_matches:
        return []

    # Dedupe by offset. If two strategies fired at the same char position,
    # keep the one with the longer / more-qualified rule id.
    by_offset: dict[int, str] = {}
    for offset, rule_id in all_matches:
        prev = by_offset.get(offset)
        if prev is None or len(rule_id) > len(prev):
            by_offset[offset] = rule_id

    return sorted(by_offset.items(), key=lambda x: x[0])


def _detect_hierarchical_anchors(text: str) -> list[tuple[int, str]]:
    """Detect anchors in flat-per-line rulebooks; synthesize qualified rule ids.

    Walks all Roman / letter / digit anchors in document order, keeping the
    most recent tag at each level in a small `path` list. Each anchor emits
    a joined rule id built from the current path:

        I.  Introduction        -> path = ["I"]              rule_id = "I"
        A.  Description ...     -> path = ["I", "A"]         rule_id = "I.A"
        1.  Foo                 -> path = ["I", "A", "1"]    rule_id = "I.A.1"
        B.  Purpose             -> path = ["I", "B"]         rule_id = "I.B"  (digit reset)

    THE SINGLE-CHAR ROMAN AMBIGUITY

        A line beginning with "C." could plausibly be either Roman C (=100)
        or subsection letter C. Real documents overwhelmingly use it as the
        subsection letter — no rulebook labels its 100th section. Two rules
        together resolve this correctly:

            1. Multi-char Roman ("II", "III", "IV" ...) is unambiguous —
               always accept as Roman.
            2. Single-char Roman ("I", "V", "X", "L", "C") is accepted as
               Roman only when it CONTINUES the section sequence (first
               ever OR previous_roman + 1). Otherwise it's a subsection
               letter.

    TOC POLLUTION

        A rulebook's table of contents lists every section once before the
        body does — so "I. Introduction 3" fires an anchor at offset ~100,
        and the real "I. Introduction" fires again at offset ~2500. We
        dedupe the final rule-id list keeping the LAST occurrence, which
        drops the TOC entries in favor of the real body anchors.
    """
    events: list[tuple[int, int, str]] = []
    for level, pat in _HIER_LEVELS:
        for m in pat.finditer(text):
            events.append((m.start(), level, m.group(1)))
    events.sort(key=lambda e: e[0])

    # Group by offset — same position may have multiple candidates.
    buckets: dict[int, list[tuple[int, str]]] = {}
    for offset, level, tag in events:
        buckets.setdefault(offset, []).append((level, tag))

    path: list[str | None] = [None, None, None]
    current_roman: int | None = None
    anchors: list[tuple[int, str]] = []

    for offset in sorted(buckets):
        level, tag = _choose_candidate(buckets[offset], current_roman)
        path[level] = tag
        for i in range(level + 1, len(path)):
            path[i] = None
        if level == 0:
            current_roman = _roman_to_int(tag)
        rule_id = ".".join(p for p in path if p is not None)
        anchors.append((offset, rule_id))

    # Dedupe by rule_id keeping the LAST occurrence — see docstring.
    seen_last: dict[str, int] = {}
    for offset, rule_id in anchors:
        seen_last[rule_id] = offset
    return sorted(((off, rid) for rid, off in seen_last.items()), key=lambda x: x[0])


def _choose_candidate(
    candidates: list[tuple[int, str]],
    current_roman: int | None,
) -> tuple[int, str]:
    """Pick the right (level, tag) when multiple regex hits share one offset."""
    # 1. Multi-char Roman is unambiguous.
    for level, tag in candidates:
        if level == 0 and len(tag) > 1:
            return (level, tag)
    # 2. Single-char Roman only wins if it continues the section sequence.
    for level, tag in candidates:
        if level == 0:
            n = _roman_to_int(tag)
            if current_roman is None or (n is not None and n == current_roman + 1):
                return (level, tag)
            break  # there's at most one Roman candidate per offset
    # 3. Otherwise prefer the most specific interpretation (digit > letter).
    return max(candidates, key=lambda c: c[0])


_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "M": 1000}


def _roman_to_int(s: str) -> int | None:
    total = 0
    prev = 0
    for ch in reversed(s):
        v = _ROMAN_VALUES.get(ch)
        if v is None:
            return None
        total += v if v >= prev else -v
        prev = v
    return total


def _split_if_long(text: str) -> list[str]:
    """Emit a single-element list if short enough; otherwise split further."""
    if len(text) <= MAX_CHARS:
        return [text]

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    out: list[str] = []
    buf: list[str] = []
    buf_len = 0

    def flush():
        nonlocal buf, buf_len
        if buf:
            out.append("\n\n".join(buf))
            buf, buf_len = [], 0

    for p in paragraphs:
        needed = len(p) + (2 if buf else 0)
        if buf_len + needed <= MAX_CHARS:
            buf.append(p)
            buf_len += needed
            continue
        flush()
        if len(p) <= MAX_CHARS:
            buf = [p]
            buf_len = len(p)
        else:
            out.extend(_hard_cut(p))
    flush()
    return out


def _hard_cut(text: str) -> list[str]:
    out = []
    step = MAX_CHARS - SPLIT_OVERLAP
    i = 0
    while i < len(text):
        out.append(text[i : i + MAX_CHARS])
        i += step
    return out


def _fallback_per_page(pages: list[PageText], *, source: str, sport: str) -> list[Chunk]:
    return [
        Chunk(
            source=source,
            sport=sport,
            rule_id=f"page-{p.page_number}",
            page_start=p.page_number,
            page_end=p.page_number,
            text=p.text.strip(),
            ordinal=i,
        )
        for i, p in enumerate(pages)
        if len(p.text.strip()) >= MIN_CHARS
    ]
