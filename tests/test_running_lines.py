# Copyright (c) 2026 Eric Cooper.
"""Running headers and footers are stripped from extracted PDF pages."""

from __future__ import annotations

from rulebook.ingest import strip_running_lines


def _page(n: int, body: str) -> str:
    header = f"Page   July 2025 {n}" if n % 2 == 0 else f"July 2025  Page   {n}"
    return f"{header}\n{body}\nLaws of the Game   Page {n} of 9"


WORDS = ["sheet", "stones", "teams", "delivery", "sweeping", "scoring", "timing", "umpires", "equipment"]
BODIES = [f"The {w} rule opens here.\nIt continues about the {w}." for w in WORDS]


def test_alternating_headers_and_a_footer_are_removed():
    out = strip_running_lines([_page(n, b) for n, b in enumerate(BODIES, start=1)])
    assert out == BODIES


def test_a_line_mid_page_is_kept_even_if_it_repeats():
    pages = [f"top\n{b}\nLaws of the Game Page {n} of 9\nmore\ntext\nend"
             for n, b in enumerate(BODIES, start=1)]
    assert strip_running_lines(pages) == pages


def test_bare_page_numbers_and_single_words_are_kept():
    # The chunker reads a bare page number as a boundary; word-per-line text puts
    # a single word at many page edges by chance.
    pages = [f"{n}\nThe\n{b}\nthe\n{n}" for n, b in enumerate(BODIES, start=1)]
    assert strip_running_lines(pages) == pages


def test_a_line_on_few_pages_is_kept():
    pages = [f"Laws of the Game Page {n}\n{b}" if n <= 2 else b
             for n, b in enumerate(BODIES, start=1)]
    assert strip_running_lines(pages) == pages
