# Copyright (c) 2026 Eric Cooper.
"""One-command ingest: add a ruleset and build its index in a single step.

    uv run python -m rulebook.add tennis ~/Downloads/itf-rules-of-tennis.pdf
    uv run python -m rulebook.add hearts rules/hearts/           # a directory of docs

What it does, so you don't have to run the four manual steps yourself:

    1. Copies the file(s) you point it at into `rules/<slug>/`.
    2. Runs the canonical builder (`scripts/build_index.py --domain <slug>`),
       which ingests -> chunks -> embeds -> writes the per-domain index.

Then ask against it:

    uv run python -m rulebook.ask "..." --domain <slug>

DOWNLOADS STAY MANUAL BY DESIGN. This command does not fetch from a URL — you
download each ruleset yourself, accepting its publisher's terms (see
rules/SOURCES.md for a menu of where to get recognizable rulesets). Copyrighted
source docs stay untracked; only the two committed sample domains (checkers,
cornhole) ship in git. Registering a display name/sources (scripts/domains.py)
is a hosted-only step — locally a domain just uses its title-cased slug.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .config import settings

# Same suffixes scripts/build_index.py ingests.
_SOURCE_SUFFIXES = {".pdf", ".md", ".txt"}
_VALID_SLUG = re.compile(r"[a-z0-9][a-z0-9_-]*")


def _collect(src: Path) -> list[Path]:
    """The ingestable files at `src` — the file itself, or a directory's contents."""
    if src.is_dir():
        return sorted(
            p for p in src.iterdir()
            if p.is_file() and p.suffix.lower() in _SOURCE_SUFFIXES
        )
    if src.is_file() and src.suffix.lower() in _SOURCE_SUFFIXES:
        return [src]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m rulebook.add",
        description="Copy a ruleset into rules/<slug>/ and build its index.",
    )
    parser.add_argument("slug", help="domain slug, lowercase (e.g. tennis, water_polo)")
    parser.add_argument("path", type=Path, help="a rule doc (.pdf/.md/.txt) or a directory of them")
    args = parser.parse_args(argv)

    if not _VALID_SLUG.fullmatch(args.slug):
        print(
            f"error: {args.slug!r} is not a valid slug — use lowercase letters, "
            "digits, '-' or '_' (e.g. water_polo).",
            file=sys.stderr,
        )
        return 2

    sources = _collect(args.path)
    if not sources:
        print(
            f"error: no .pdf/.md/.txt files at {args.path}. Point me at a rule "
            "document or a directory containing one.",
            file=sys.stderr,
        )
        return 2

    dest = settings.repo_root / "rules" / args.slug
    dest.mkdir(parents=True, exist_ok=True)
    for src in sources:
        target = dest / src.name
        shutil.copy2(src, target)
        print(f"[copy ]  {src}  ->  {target.relative_to(settings.repo_root)}")

    # Reuse the one true builder for this domain only, with the same interpreter —
    # no second build path to drift from scripts/build_index.py.
    builder = settings.repo_root / "scripts" / "build_index.py"
    print(f"[build]  {args.slug}: running {builder.name} --domain {args.slug}\n")
    result = subprocess.run(
        [sys.executable, str(builder), "--domain", args.slug],
        cwd=settings.repo_root,
    )
    if result.returncode != 0:
        print(f"\nerror: build failed for {args.slug!r} (see output above).", file=sys.stderr)
        return result.returncode

    print(
        f"\n[done ]  {args.slug} is indexed. Ask it:\n"
        f'    uv run python -m rulebook.ask "..." --domain {args.slug}'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
