# Copyright (c) 2026 Eric Cooper.
"""page_links: notebook links go to Colab in the notebooks and to the pages on the site."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

NOTEBOOKS = Path(__file__).parents[1] / "notebooks"
_spec = importlib.util.spec_from_file_location("page_links", NOTEBOOKS / "page_template" / "page_links.py")
page_links = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(page_links)

COLAB = page_links.COLAB


def test_prose_link_goes_to_the_page():
    html = f'<a href="{COLAB}evaluation.ipynb" target="_parent">A closer look at Evaluation</a>'
    assert page_links.to_pages(html) == '<a href="evaluation.html" target="_parent">A closer look at Evaluation</a>'


def test_colab_links_are_kept():
    html = (
        f'(<a href="{COLAB}reranking.ipynb" target="_parent">run it in Colab</a>) '
        f'<a class="colab" href="{COLAB}chunking.ipynb">Run it in Colab</a>'
    )
    assert page_links.to_pages(html) == html


def test_other_links_are_untouched():
    html = '<a href="https://ecoop.github.io/rulebook/">notebooks page</a> <a href="https://example.com/x.ipynb">x</a>'
    assert page_links.to_pages(html) == html


def test_notebooks_link_each_other_through_colab():
    # Colab turns any other link into a google.com "Redirect Notice" stop.
    for nb in NOTEBOOKS.glob("*.ipynb"):
        text = "".join("".join(c["source"]) for c in json.loads(nb.read_text())["cells"])
        assert not re.search(r"ecoop\.github\.io/rulebook/\w+\.html", text), nb.name
