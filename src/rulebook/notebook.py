# Copyright (c) 2026 Eric Cooper.
"""Notebook support: one `setup()` call and a table helper, so the teaching notebooks
can start with two lines instead of a screen of boilerplate.

    from rulebook.notebook import setup, show_table
    setup()

Nothing in the app imports this module. IPython is imported only inside `show_table`,
so importing the module works without the notebook dependencies installed.
"""

from __future__ import annotations

import html
import os
import re
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

from . import app_state
from .config import Settings, settings
from .store import list_domains


def setup() -> None:
    """Get a notebook ready to run, from wherever Jupyter (or Colab) was started.

    - Work from the repo root, so `rules/`, `data/` and `eval/` resolve.
    - Load the repo's `.env` if there is one. setup() never reads API keys from
      anywhere else; a notebook that needs one asks for it in a visible cell.
    - Start the cost tracking that embedding and generation calls report to.

    It builds no index: a notebook builds the indexes it needs in a visible cell
    (`build_index` or `ensure_index`), where the work belongs.
    """
    root = settings.repo_root
    os.chdir(root)
    if load_dotenv(root / ".env"):
        _reload_settings()
    app_state.initialize(settings)
    print(f"ready: working in {root.name}/")


def _reload_settings() -> None:
    """Re-read settings now that `.env` is loaded.

    `settings` was created when `rulebook` was first imported, possibly before the
    working directory was the repo root, so it may have missed `.env`. Update it in
    place, because other modules hold a reference to this same object.
    """
    fresh = Settings()  # type: ignore[call-arg]
    for name in Settings.model_fields:
        setattr(settings, name, getattr(fresh, name))


# The build log's per-stage lines, the ones worth showing in a notebook. The rest
# (which files were found, a page count, the closing summary) is left out.
_STAGE_LINE = re.compile(r"^\[(ingest|chunk|embed|store)\s*\]")


def build_index(*domains: str) -> None:
    """Build each sample domain's index (key-free, a few seconds each), showing its stages.

    Runs scripts/build_index.py and prints just its per-stage lines: ingest, chunk,
    embed, store. Rebuilds an index that already exists.
    """
    for domain in domains:
        build = subprocess.run(
            [sys.executable, "scripts/build_index.py", "--domain", domain],
            capture_output=True, text=True,
        )
        if build.returncode:
            raise RuntimeError(build.stderr)
        lines = [ln for ln in build.stdout.splitlines() if _STAGE_LINE.match(ln)]
        print("\n".join(lines).replace(str(Path.cwd()), "."))  # paths relative to the repo


def ensure_index(*domains: str) -> None:
    """Build each sample domain's index if it isn't built yet (see `build_index`)."""
    for domain in domains:
        if domain in list_domains(settings.resolved_index_path):
            print(f"{domain}: index already built")
        else:
            build_index(domain)


def hit_cell(result, k: int) -> str:
    """A hit@k table cell with the count behind it: ``"0.59 (13/22)"``.

    ``result`` is an :class:`rulebook.eval.EvalResult`. The count reads more
    plainly than the fraction on a small gold set: 13 of 22 questions had a cited
    rule in the top k.
    """
    # Pad the count with figure spaces (as wide as a digit), so "( 6/12)" and
    # "(10/12)" line up in a right-aligned column.
    hits = str(result.hits_at(k)).rjust(len(str(result.n)), "\u2007")
    return f"{result.hit_rate_at(k):.2f} ({hits}/{result.n})"


def show_table(headers, rows) -> None:
    """Render rows as a real table: a grid of cells, numeric columns right-aligned.

    Plain HTML using both the old `border`/`align` attributes and inline styles, so
    it looks like a table in JupyterLab, Colab, VS Code and on GitHub alike.
    A value written as **like this** is shown in bold.
    """
    from IPython.display import HTML, display

    def is_number(v):
        # A number, or a number followed by a note: "0.59 (13/22)".
        try:
            float(str(v).split(" (")[0])
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
