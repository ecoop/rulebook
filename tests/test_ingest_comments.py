# Copyright (c) 2026 Eric Cooper.
"""Markdown HTML comments (license headers, notes) never reach the index."""

from __future__ import annotations

from pathlib import Path

from rulebook.chunking import chunk_pages
from rulebook.ingest import extract_pages

RULES_ROOT = Path(__file__).resolve().parents[1] / "rules"


def test_html_comments_are_stripped_from_markdown(tmp_path: Path) -> None:
    doc = tmp_path / "x.md"
    doc.write_text(
        "<!--\nCopyright (c) 2026 Someone.\nmulti-line note\n-->\n\n"
        "# Title\n\nIntro text. <!-- inline note --> More intro.\n"
    )
    [page] = extract_pages(doc)
    assert "Copyright" not in page.text
    assert "inline note" not in page.text
    assert "<!-" not in page.text
    assert page.text.lstrip().startswith("# Title")
    assert "Intro text." in page.text and "More intro." in page.text


def test_plain_text_is_left_alone(tmp_path: Path) -> None:
    # .txt isn't Markdown, so "<!--" there is literal text, not a comment.
    doc = tmp_path / "x.txt"
    doc.write_text("Literal <!-- kept --> text.\n")
    [page] = extract_pages(doc)
    assert "<!-- kept -->" in page.text


def test_sample_corpora_index_no_license_header() -> None:
    for domain in ("checkers", "tennis", "poker"):
        doc = RULES_ROOT / domain / f"{domain}.md"
        chunks = chunk_pages(extract_pages(doc), source=doc.name, domain=domain)
        assert chunks, domain
        for c in chunks:
            assert "Copyright" not in c.text, f"{domain} {c.rule_id} still carries the header"
            assert "<!-" not in c.text, f"{domain} {c.rule_id} has comment debris"
