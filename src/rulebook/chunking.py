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
       its rule id, page range, domain, and source PDF.

    4. If a section is longer than MAX_CHARS, split it further at
       sentence ends, so no piece stops mid-sentence and no single chunk
       becomes needle-in-a-haystack.

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
    domain: str         # "ultimate" | "goaltimate" | ...
    rule_id: str       # e.g. "II.B.1"; "preamble" for pre-first-rule text
    page_start: int    # 1-indexed page numbers
    page_end: int
    text: str
    ordinal: int = 0   # index within the domain, assigned after chunking


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

# NUMBERED-TITLE pattern — rules written as "R13. INTERRUPTED GAMES": a prefixed
# number followed by an ALL-CAPS title (the World Curling rules). PDF extraction
# frequently flattens these off the line start (only ~5 of 19 curling rules land
# at ^), so — unlike every pattern above — we match ANYWHERE and lean on the caps
# title as the low-false-positive signal. A bare cross-reference ("see R6.") is
# followed by prose ("R6. The …"), whose second title char is lowercase, so it
# doesn't match. Group 1 is the rule id (e.g. "R6").
_NUMBERED_TITLE = re.compile(r"\b(R\d+)\.\s+[A-Z][A-Z]+(?:[A-Z '&/-]*[A-Z])?")

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
#
# Roman numerals run up to 7 chars ("XXXVIII") — a 4-char cap silently
# dropped "XVIII." and folded that whole section into XVII. Appendices
# ("Appendix B: Guidelines…") are top-level too, so their A./1. clauses don't
# land under (and, via the keep-last dedupe, overwrite) the last roman section.
_HIER_LEVELS = [
    (0, re.compile(r"^\s*([IVXLC]{1,7})\.\s+(?=[A-Z])", re.M)),   # I. II. XVIII.
    (0, re.compile(r"^\s*(Appendix\s+[A-Z])\s*:", re.M)),          # Appendix B:
    (1, re.compile(r"^\s*([A-Z])\.\s+(?=[A-Za-z])", re.M)),        # A. B. C.
    (2, re.compile(r"^\s*(\d{1,3})\.\s+(?=[A-Za-z])", re.M)),      # 1. 2. 3.
]

MAX_CHARS = 1500       # ~350 tokens; comfortably under any embedder's cap
MIN_CHARS = 60         # discard shorter fragments (headings-only, page numbers)

_WHITESPACE_RUN = re.compile(r"\s+")


def _normalize_ws(text: str) -> str:
    """Collapse whitespace runs to single spaces for a chunk's stored text.

    pypdf extracts some text pages one word per line (``word\\n \\nword``);
    anchor detection runs on the raw joined text (so rule ids stay correct),
    but the text we store *and embed* per chunk should read as prose — clean
    text embeds better (retrieval quality) and renders cleanly in the
    passages panel. Applied after section splitting, so paragraph structure
    is only used for splitting, not preserved in the chunk body. (The serving
    path has a twin in retrieve._normalize_ws as a belt-and-suspenders.)
    """
    return _WHITESPACE_RUN.sub(" ", text).strip()


def chunk_pages(pages: list[PageText], *, source: str, domain: str) -> list[Chunk]:
    """Chunk a list of PageText into a list of Chunk records."""
    if not pages:
        return []

    joined, page_starts = _join_with_offsets(pages)
    anchors = _detect_anchors(joined)

    if not anchors:
        # No rule-numbering scheme — try markdown headings (authored prose rules
        # like the card/board games use ## sections, not clause numbers).
        anchors = _detect_markdown_heading_anchors(joined)

    if not anchors:
        # Nothing structural detected — degrade gracefully to per-page chunks.
        return _fallback_per_page(pages, source=source, domain=domain)

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
                        domain=domain,
                        rule_id="preamble",
                        page_start=1,
                        page_end=page_end,
                        text=_normalize_ws(piece),
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
                    domain=domain,
                    rule_id=rule_id,
                    page_start=page_start,
                    page_end=page_end,
                    text=_normalize_ws(piece),
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

    numbered_title = _detect_numbered_title_anchors(text)
    if len(numbered_title) >= MIN_ANCHORS_TO_TRUST:
        all_matches.extend(numbered_title)

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


def _detect_numbered_title_anchors(text: str) -> list[tuple[int, str]]:
    """Detect "R13. INTERRUPTED GAMES"-style rules matched anywhere (not just ^).

    Deduped by rule id keeping the LAST occurrence — a rulebook lists every rule
    in its table of contents before the body, so the TOC copies come first and
    the real body definition is last (the same TOC-pollution fix the
    hierarchical detector uses).
    """
    seen_last: dict[str, int] = {}
    for m in _NUMBERED_TITLE.finditer(text):
        seen_last[m.group(1)] = m.start()
    return sorted(((off, rid) for rid, off in seen_last.items()), key=lambda x: x[0])


_MD_HEADING = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", re.M)


def _detect_markdown_heading_anchors(text: str) -> list[tuple[int, str]]:
    """Split an ATX-markdown document at its headings; the heading text is the
    chunk's rule_id (section-based citation for prose-organized rules).

    Deliberately called only after every rule-numbering strategy comes up empty,
    so it never perturbs numbered rulebooks that happen to contain a stray '#'.
    Used by the authored public-domain game rules (hearts, backgammon), whose
    sections are named ("The Deal", "Bearing Off") rather than numbered.
    """
    out: list[tuple[int, str]] = []
    for m in _MD_HEADING.finditer(text):
        title = m.group(1).strip()
        if title:
            out.append((m.start(), title))
    return out


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
            2. Single-char Roman ("I", "V", "X", "L", "C") is a subsection
               letter when it CONTINUES the letter sequence ("V." after
               "U."). Otherwise it's Roman when it continues the section
               sequence (first ever OR previous_roman + 1). Otherwise it's
               a letter.

    TOC POLLUTION

        A rulebook's table of contents lists every section once before the
        body does — so "I. Introduction 3" fires an anchor at offset ~100,
        and the real "I. Introduction" fires again at offset ~2500. Entries
        that read as a TOC line (a short title, then a page number) are
        dropped up front: left in, the TOC's last "XXI." made the body's
        "I. Introduction" look like letter I of section XXI. Any that slip
        through are handled by deduping the final rule-id list keeping the
        LAST occurrence, which favors the real body anchors.
    """
    events: list[tuple[int, int, str]] = []
    for level, pat in _HIER_LEVELS:
        for m in pat.finditer(text):
            tag = _WHITESPACE_RUN.sub(" ", m.group(1))
            if tag.startswith("Appendix") and not _starts_sentence(text, m.start()):
                continue  # a cross-reference ("pursuant to Appendix B: …")
            events.append((m.start(), level, tag))
    events.sort(key=lambda e: e[0])

    events = _drop_toc_entries(text, events)

    # Group by offset — same position may have multiple candidates.
    buckets: dict[int, list[tuple[int, str]]] = {}
    for offset, level, tag in events:
        buckets.setdefault(offset, []).append((level, tag))

    path: list[str | None] = [None, None, None]
    current_roman: int | None = None
    anchors: list[tuple[int, str]] = []

    for offset in sorted(buckets):
        candidates = buckets[offset]
        if current_roman is None:
            # "Appendix B:" is a top-level heading only in roman-sectioned
            # rulebooks; elsewhere it would re-parent every later clause.
            candidates = [c for c in candidates if not c[1].startswith("Appendix")]
            if not candidates:
                continue
        level, tag = _choose_candidate(candidates, current_roman, path[1])
        path[level] = tag
        for i in range(level + 1, len(path)):
            path[i] = None
        if level == 0 and _roman_to_int(tag) is not None:
            current_roman = _roman_to_int(tag)
        rule_id = ".".join(p for p in path if p is not None)
        anchors.append((offset, rule_id))

    # Dedupe by rule_id keeping the LAST occurrence — see docstring.
    seen_last: dict[str, int] = {}
    for offset, rule_id in anchors:
        seen_last[rule_id] = offset
    return sorted(((off, rid) for rid, off in seen_last.items()), key=lambda x: x[0])


# A table-of-contents line once its anchor is stripped: a short title with no
# sentence punctuation, dot leaders, then a page number ("Etiquette ..... 42").
_TOC_LINE = re.compile(r"[^.!?]{1,80}?\s*\d{1,3}")
_DOT_LEADER = re.compile(r"\.{2,}")


def _drop_toc_entries(
    text: str, events: list[tuple[int, int, str]]
) -> list[tuple[int, int, str]]:
    """Remove anchors whose span up to the next anchor is just a TOC line."""
    events = sorted(events, key=lambda e: e[0])
    kept: list[tuple[int, int, str]] = []
    for i, (offset, level, tag) in enumerate(events):
        end = next((e[0] for e in events[i + 1 :] if e[0] > offset), len(text))
        span = text[offset:end]
        # Drop the anchor itself ("XXI." / "Appendix B:"), then dot leaders.
        span = span.lstrip().removeprefix(tag.split(" ")[0])
        span = _WHITESPACE_RUN.sub(" ", _DOT_LEADER.sub(" ", span.lstrip(".: \n")))
        if level == 0 and _TOC_LINE.fullmatch(span.strip()):
            continue
        kept.append((offset, level, tag))
    return kept


def _starts_sentence(text: str, offset: int) -> bool:
    """True if ``offset`` follows a sentence end, a page number or nothing.

    Word-per-line extraction puts every word at a line start, so "^" alone
    can't tell a heading from a mid-sentence mention of the same words.
    """
    before = text[:offset].rstrip()
    return not before or before[-1] in ".!?:;)]" or before[-1].isdigit()


def _choose_candidate(
    candidates: list[tuple[int, str]],
    current_roman: int | None,
    current_letter: str | None,
) -> tuple[int, str]:
    """Pick the right (level, tag) when multiple regex hits share one offset."""
    # 1. Multi-char Roman (and "Appendix B") is unambiguous.
    for level, tag in candidates:
        if level == 0 and len(tag) > 1:
            return (level, tag)
    # 2. A single char that continues the letter sequence is a letter.
    for level, tag in candidates:
        if level == 1 and current_letter and ord(tag) == ord(current_letter) + 1:
            return (level, tag)
    # 3. Otherwise single-char Roman wins if it continues (or restarts) the
    #    section sequence.
    for level, tag in candidates:
        if level == 0:
            n = _roman_to_int(tag)
            if current_roman is None or (n is not None and n == current_roman + 1):
                return (level, tag)
            break  # there's at most one Roman candidate per offset
    # 4. Otherwise prefer the most specific interpretation (digit > letter).
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


# A sentence ends at . ! or ? — optionally closed by a quote, paren or the
# rulebook's "[[annotation]]" brackets — followed by whitespace.
_SENTENCE_END = re.compile(r"(?<=[.!?])[\"”’)\]]*\s+")


def _split_if_long(text: str) -> list[str]:
    """Emit a single-element list if short enough; otherwise pack whole
    sentences into pieces of at most MAX_CHARS.

    Splits at sentence ends, not paragraph breaks: pypdf extracts some
    rulebooks one word per paragraph (``word\\n\\nword``), so a paragraph
    break there is just a word break and packing paragraphs cut sections
    mid-sentence ("…when the goaltending count reaches" | "three, this is a
    goaltending violation"). A single sentence over MAX_CHARS falls back to
    word-boundary cuts.
    """
    if len(text) <= MAX_CHARS:
        return [text]

    sentences = [s for s in _SENTENCE_END.split(_normalize_ws(text)) if s]
    out: list[str] = []
    buf = ""
    for sent in sentences:
        if len(sent) > MAX_CHARS:
            if buf:
                out.append(buf)
                buf = ""
            out.extend(_word_cut(sent))
        elif not buf:
            buf = sent
        elif len(buf) + 1 + len(sent) <= MAX_CHARS:
            buf += " " + sent
        else:
            out.append(buf)
            buf = sent
    if buf:
        out.append(buf)
    return out


def _word_cut(text: str) -> list[str]:
    """Cut an over-long sentence at word boundaries into <= MAX_CHARS pieces."""
    out: list[str] = []
    buf = ""
    for word in text.split(" "):
        if buf and len(buf) + 1 + len(word) > MAX_CHARS:
            out.append(buf)
            buf = word
        else:
            buf = f"{buf} {word}" if buf else word
    if buf:
        out.append(buf)
    return out


def _fallback_per_page(pages: list[PageText], *, source: str, domain: str) -> list[Chunk]:
    return [
        Chunk(
            source=source,
            domain=domain,
            rule_id=f"page-{p.page_number}",
            page_start=p.page_number,
            page_end=p.page_number,
            text=_normalize_ws(p.text),
            ordinal=i,
        )
        for i, p in enumerate(pages)
        if len(p.text.strip()) >= MIN_CHARS
    ]
