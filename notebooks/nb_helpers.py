# Copyright (c) 2026 Eric Cooper.
"""Small helpers shared by the notebooks: building the sample index and showing tables.

These are for the notebooks only; they aren't part of the `rulebook` package.
"""

from __future__ import annotations

import html
import re
import subprocess
import sys
from pathlib import Path

from IPython.display import HTML, display

from rulebook.config import settings
from rulebook.store import list_domains


def ensure_index(*domains: str) -> None:
    """Build each sample domain's index if it isn't built yet (key-free, a few seconds)."""
    for domain in domains:
        if domain in list_domains(settings.resolved_index_path):
            print(f"{domain}: index already built")
            continue
        print(f"{domain}: building the index...")
        build = subprocess.run(
            [sys.executable, "scripts/build_index.py", "--domain", domain],
            capture_output=True, text=True,
        )
        print(build.stdout.replace(str(Path.cwd()), "."))  # the build log, paths relative to the repo
        if build.returncode:
            raise RuntimeError(build.stderr)


def show_table(headers, rows) -> None:
    """Render rows as a real table: a grid of cells, numeric columns right-aligned.

    Plain HTML using both the old `border`/`align` attributes and inline styles, so
    it looks like a table in JupyterLab, Colab, VS Code and on GitHub alike.
    A value written as **like this** is shown in bold.
    """
    def is_number(v):
        try:
            float(str(v))
            return True
        except ValueError:
            return False

    aligns = ["right" if rows and all(is_number(r[i]) for r in rows) else "left"
              for i in range(len(headers))]

    def cell(tag, v, align):
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(str(v)))
        return (f'<{tag} align="{align}" style="text-align:{align}; padding:4px 10px; '
                f'border:1px solid #bbb">{text}</{tag}>')

    head = "".join(cell("th", h, a) for h, a in zip(headers, aligns, strict=True))
    body = "".join(
        "<tr>" + "".join(cell("td", v, a) for v, a in zip(row, aligns, strict=True)) + "</tr>"
        for row in rows
    )
    display(HTML('<table border="1" cellpadding="4" style="border-collapse:collapse">'
                 f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"))
