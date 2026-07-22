"""PDF -> a stream of (page_number, text) records.

pypdf gives us per-page text extraction that's good enough for
born-digital PDFs like these rulebooks. If we ever have to handle a
scanned PDF, we'd swap in OCR (e.g. pytesseract) here — but the
interface downstream stays the same, so nothing else has to change.

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


def extract_pages(pdf_path: Path) -> list[PageText]:
    """Return one PageText per non-empty page."""
    reader = PdfReader(pdf_path)
    out: list[PageText] = []
    for idx, page in enumerate(reader.pages, start=1):
        raw = page.extract_text() or ""
        cleaned = _clean(raw)
        if cleaned.strip():
            out.append(PageText(page_number=idx, text=cleaned))
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
