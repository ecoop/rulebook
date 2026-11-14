# Copyright (c) 2026 Eric Cooper.
"""One-command ingest: add a ruleset and build its index in a single step.

    uv run python -m rulebook.add tennis ~/Downloads/itf-rules-of-tennis.pdf
    uv run python -m rulebook.add hearts rules/hearts/           # a directory of docs
    uv run python -m rulebook.add ultimate 1990 ~/Downloads/ultimate-1990.pdf   # an edition
    uv run python -m rulebook.add ultimate --edition 1990 ~/Downloads/ultimate-1990.pdf

Editions (see docs/design/ruleset-editions.md). A game with one edition stays
flat (`rules/ultimate/`). Adding a different edition to a flat game first moves
its files into a labelled folder (`rules/ultimate/2026/`, label from
`--existing-edition`, the label recorded when it was added, or a prompt) and
keeps their slug through the folder's `.ruleset.json` marker; the new files go
to `rules/ultimate/1990/` with slug `ultimate_1990`. Nothing is deleted.

What it does, so you don't have to run the four manual steps yourself:

    1. Copies the file(s) you point it at into `rules/<slug>/` (or the
       edition's folder).
    2. Runs the canonical builder (`scripts/build_index.py --domain <slug>`),
       which ingests -> chunks -> embeds -> writes the per-domain index.
       `--no-build` stops after the copy.

Then ask against it:

    uv run python -m rulebook.ask "..." --domain <slug>

DOWNLOADS STAY MANUAL BY DESIGN. This command does not fetch from a URL — you
download each ruleset yourself, accepting its publisher's terms (see
rules/SOURCES.md for a menu of where to get recognizable rulesets). Copyrighted
source docs stay untracked; only the committed sample domains (checkers,
tennis, poker) ship in git. Registering a display name/sources (scripts/domains.py)
is a hosted-only step — locally a domain just uses its title-cased slug.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from .config import settings
from .rulesets import (
    SOURCE_SUFFIXES,
    VALID_SLUG,
    derived_slug,
    discover,
    nest_flat,
    normalize_label,
    read_marker,
    rule_files,
    write_marker,
)


class AddError(Exception):
    """A user-facing refusal; printed as `error: ...`, exit 2."""


def _rules_root() -> Path:
    return settings.repo_root / "rules"


def _collect(src: Path) -> list[Path]:
    """The ingestable files at `src` — the file itself, or a directory's contents."""
    if src.is_dir():
        return sorted(
            p for p in src.iterdir()
            if p.is_file() and p.suffix.lower() in SOURCE_SUFFIXES
        )
    if src.is_file() and src.suffix.lower() in SOURCE_SUFFIXES:
        return [src]
    return []


def _ask_existing_label(game: str) -> str:
    if not sys.stdin.isatty():
        raise AddError(
            f"rules/{game}/ is flat with no edition label recorded. Pass "
            f"--existing-edition <label> to name the edition its files are."
        )
    label = input(f"rules/{game}/ already holds one edition. Label for it (e.g. 2026): ").strip()
    if not label:
        raise AddError("no label given; nothing changed.")
    return label


def _check_label(label: str) -> None:
    if not normalize_label(label) or label.startswith(".") or "/" in label or label != label.strip():
        raise AddError(f"{label!r} is not a usable edition label (e.g. 1990, wfdf-2025).")


def _check_new_slug(root: Path, slug: str) -> None:
    if not VALID_SLUG.fullmatch(slug):
        raise AddError(f"edition gives slug {slug!r}, which is not a valid slug.")
    owner = discover(root).by_slug().get(slug)
    if owner is not None:
        raise AddError(f"slug {slug!r} already belongs to {owner.dir}; pick another edition label.")


def place(root: Path, game: str, edition: str | None, existing_edition: str | None) -> tuple[Path, str]:
    """Decide (and prepare) the folder the new files go in; return (folder, slug).

    May move a flat game's files into an edition folder (``nest_flat``), which
    keeps their slug. Never deletes anything.
    """
    game_dir = root / game
    flat = game_dir.is_dir() and bool(rule_files(game_dir))
    editions = sorted(
        d.name for d in (game_dir.iterdir() if game_dir.is_dir() else [])
        if d.is_dir() and not d.name.startswith(".") and rule_files(d)
    )

    if edition is None:
        if not flat and editions:
            raise AddError(
                f"{game} has editions ({', '.join(editions)}); pass --edition <label>."
            )
        game_dir.mkdir(parents=True, exist_ok=True)
        marker = read_marker(game_dir)
        return game_dir, marker["slug"] if marker else derived_slug(game)

    _check_label(edition)
    if not flat and not editions:
        # A new game: one edition stays flat; remember its label for later.
        game_dir.mkdir(parents=True, exist_ok=True)
        marker = read_marker(game_dir)
        slug = marker["slug"] if marker else derived_slug(game)
        write_marker(game_dir, slug, game, edition)
        return game_dir, slug

    if flat:
        marker = read_marker(game_dir) or {}
        current = existing_edition or marker.get("edition") or _ask_existing_label(game)
        _check_label(current)
        slug = marker.get("slug") or derived_slug(game)
        if current == edition:  # more files for the same (only) edition
            write_marker(game_dir, slug, game, edition)
            return game_dir, slug
        _check_new_slug(root, derived_slug(game, edition))
        if (game_dir / edition).exists():
            raise AddError(f"{game_dir / edition} already exists beside flat files; tidy it first.")
        moved = nest_flat(root, game, current)
        print(f"[move ]  {game}: existing files -> {moved.relative_to(root.parent)} (slug {slug!r} kept)")

    dest = game_dir / edition
    if dest.is_dir() and rule_files(dest):
        marker = read_marker(dest)
        return dest, marker["slug"] if marker else derived_slug(game, edition)
    slug = derived_slug(game, edition)
    _check_new_slug(root, slug)
    dest.mkdir(parents=True, exist_ok=True)
    write_marker(dest, slug, game, edition)
    return dest, slug


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m rulebook.add",
        description="Copy a ruleset into rules/<slug>/ (or rules/<game>/<edition>/) and build its index.",
    )
    parser.add_argument(
        "args", nargs="+", metavar="ARG",
        help="<slug> <path>, or <game> <edition> <path>; path is a rule doc "
             "(.pdf/.md/.txt) or a directory of them",
    )
    parser.add_argument("--edition", help="edition label for these files, e.g. 1990")
    parser.add_argument(
        "--existing-edition",
        help="label for a flat game's current files when this adds a second edition",
    )
    parser.add_argument("--no-build", action="store_true", help="copy only; skip the index build")
    ns = parser.parse_intermixed_args(argv)

    if len(ns.args) == 2:
        game, path, edition = ns.args[0], Path(ns.args[1]), ns.edition
    elif len(ns.args) == 3 and ns.edition is None:
        game, edition, path = ns.args[0], ns.args[1], Path(ns.args[2])
    else:
        parser.error("expected <slug> <path> or <game> <edition> <path>")

    if not VALID_SLUG.fullmatch(game):
        print(
            f"error: {game!r} is not a valid slug — use lowercase letters, "
            "digits, '-' or '_' (e.g. water_polo).",
            file=sys.stderr,
        )
        return 2

    sources = _collect(path)
    if not sources:
        print(
            f"error: no .pdf/.md/.txt files at {path}. Point me at a rule "
            "document or a directory containing one.",
            file=sys.stderr,
        )
        return 2

    root = _rules_root()
    try:
        dest, slug = place(root, game, edition, ns.existing_edition)
    except (AddError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    for src in sources:
        target = dest / src.name
        shutil.copy2(src, target)
        print(f"[copy ]  {src}  ->  {target.relative_to(root.parent)}")

    if ns.no_build:
        print(f"\n[done ]  copied into {dest.relative_to(root.parent)} (slug {slug!r}); build skipped.")
        return 0

    # Reuse the one true builder for this domain only, with the same interpreter —
    # no second build path to drift from scripts/build_index.py.
    builder = settings.repo_root / "scripts" / "build_index.py"
    print(f"[build]  {slug}: running {builder.name} --domain {slug}\n")
    result = subprocess.run(
        [sys.executable, str(builder), "--domain", slug],
        cwd=settings.repo_root,
    )
    if result.returncode != 0:
        print(f"\nerror: build failed for {slug!r} (see output above).", file=sys.stderr)
        return result.returncode

    print(
        f"\n[done ]  {slug} is indexed. Ask it:\n"
        f'    uv run python -m rulebook.ask "..." --domain {slug}'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
