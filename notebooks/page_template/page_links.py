# Copyright (c) 2026 Eric Cooper.
"""Point a rendered page's links to the other notebooks at their pages, not Colab.

In the notebooks, a link to another notebook goes to its Colab copy: Colab sends
every other link through an unsigned google.com redirect that stops at a
"Redirect Notice" page, but leaves its own links alone. On the results pages
those links should stay on the site, so after rendering:

    uv run --no-sync python notebooks/page_template/page_links.py _site/*.html

rewrites them to the sibling page (embeddings.ipynb -> embeddings.html). A link
whose text says Colab ("run it in Colab") is meant to open Colab, and is kept.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

COLAB = "https://colab.research.google.com/github/ecoop/rulebook/blob/main/notebooks/"
_ANCHOR = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.S)
_HREF = re.compile(r'href="' + re.escape(COLAB) + r'([\w-]+)\.ipynb"')


def to_pages(html: str) -> str:
    """Rewrite Colab links to the other notebooks as links to their pages."""

    def fix(m: re.Match[str]) -> str:
        attrs, text = m.groups()
        if "Colab" in text:
            return m.group(0)
        attrs = _HREF.sub(r'href="\1.html"', attrs)
        return f"<a{attrs}>{text}</a>"

    return _ANCHOR.sub(fix, html)


def main(paths: list[str]) -> None:
    for path in map(Path, paths):
        path.write_text(to_pages(path.read_text()))


if __name__ == "__main__":
    main(sys.argv[1:])
