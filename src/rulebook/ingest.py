"""Source file -> a stream of (page_number, text) records.

Handles two source shapes:

    * Born-digital PDFs (rulebooks) — pypdf per-page text extraction.
    * Plain text / Markdown — read as a single "page". Used for content
      that arrived outside a PDF (a hand-written note, a vision-extracted
      diagram description from scripts/vision_extract.py, etc).

For scanned or image-only PDFs (pypdf returns zero characters), pre-run
scripts/vision_extract.py to produce a companion `.extracted.md` file
and reference that file in build_index.SOURCES instead of the PDF.

We preserve pagination because the chunker downstream needs page numbers
to attach to each chunk. Citations in the final answer point back to the
page (and section) they came from — that's what makes the RAG output
trustworthy rather than a plausibility exercise.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader


@dataclass
class PageText:
    page_number: int   # 1-indexed, matches the printed page numbers
    text: str


_TEXT_SUFFIXES = {".md", ".txt"}

# HTML comments in Markdown (license headers, editor notes) are invisible when
# the file is rendered, so they shouldn't be searchable either: left in, a
# copyright header becomes part of the first chunk and can outrank real rules.
# Stripped from the RAW text — _clean's hyphen rejoin would otherwise turn a
# "<!--" at the end of a line into "<!-" and the comment would no longer match.
_HTML_COMMENT = re.compile(r"<!--.*?-->[ \t]*\n?", re.DOTALL)


def strip_html_comments(text: str) -> str:
    """``text`` without its HTML comments (and the rest of each comment's line)."""
    return _HTML_COMMENT.sub("", text)


def extract_pages(source_path: Path) -> list[PageText]:
    """Return one PageText per non-empty page (or one per text file)."""
    if source_path.suffix.lower() in _TEXT_SUFFIXES:
        raw = source_path.read_text(encoding="utf-8")
        if source_path.suffix.lower() == ".md":
            raw = strip_html_comments(raw)
        cleaned = _clean(raw)
        return [PageText(page_number=1, text=cleaned)] if cleaned.strip() else []

    reader = PdfReader(source_path)
    texts = strip_running_lines([_clean(page.extract_text() or "") for page in reader.pages])
    return [
        PageText(page_number=idx, text=text)
        for idx, text in enumerate(texts, start=1)
        if text.strip()
    ]


# A running header or footer is the same line at the top or bottom of many pages,
# differing only in its numbers ("Page 4 of 14", "July 2025 Page 5"). Left in, it
# lands mid-rule in every chunk that crosses a page break and puts the same words
# into dozens of vectors.
_EDGE_LINES = 2          # look at the first and last two non-empty lines of a page
_RUNNING_SHARE = 1 / 3   # on at least this share of pages (odd/even headers alternate)
_DIGITS = re.compile(r"\d+")
_WORD = re.compile(r"[A-Za-z]{2,}")


def _running_key(line: str) -> str:
    return _DIGITS.sub("#", " ".join(line.split()))


def strip_running_lines(pages: list[str]) -> list[str]:
    """``pages`` without their running headers and footers.

    A line is running when it sits within ``_EDGE_LINES`` of the top or bottom of
    at least three pages and ``_RUNNING_SHARE`` of all pages, comparing lines with
    their numbers masked. It must have two words, so a bare page number (which the
    chunker reads as a boundary between rules) and a stray word that a
    word-per-line extraction happens to put at a page edge are left alone.
    """
    edges = []
    for text in pages:
        lines = [line for line in text.splitlines() if line.strip()]
        edges.append({_running_key(line) for line in lines[:_EDGE_LINES] + lines[-_EDGE_LINES:]})
    counts: dict[str, int] = {}
    for keys in edges:
        for key in keys:
            counts[key] = counts.get(key, 0) + 1
    floor = max(3, len(pages) * _RUNNING_SHARE)
    running = {k for k, n in counts.items() if n >= floor and len(_WORD.findall(k)) >= 2}
    if not running:
        return pages

    out = []
    for text in pages:
        lines = text.splitlines()
        filled = [i for i, line in enumerate(lines) if line.strip()]
        edge = set(filled[:_EDGE_LINES] + filled[-_EDGE_LINES:])
        out.append("\n".join(
            line for i, line in enumerate(lines)
            if not (i in edge and _running_key(line) in running)
        ).strip("\n"))
    return out


# ---------------------------------------------------------------------------

_HYPHEN_LINEBREAK = re.compile(r"-\n(\w)")
_TOO_MANY_BLANKS = re.compile(r"\n{3,}")


def _clean(text: str) -> str:
    """Normalize whitespace and common PDF-extraction artifacts.

    We only fix the ones that actively hurt chunking or retrieval:

    * Rejoin hyphenated line breaks — "goal-\ntimate" -> "goaltimate".
      Otherwise the embedder sees two half-words instead of one term.

    * Collapse runs of blank lines. Retrieval doesn't care about them and
      they can push semi-related paragraphs across the same chunk boundary.

    * Strip trailing whitespace so chunk boundary heuristics don't miss.
    """
    text = _HYPHEN_LINEBREAK.sub(r"\1", text)
    text = _TOO_MANY_BLANKS.sub("\n\n", text)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return text
