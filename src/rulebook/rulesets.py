# Copyright (c) 2026 Eric Cooper.
"""Ruleset discovery: which folders under ``rules/`` are rulesets, and their slugs.

A **ruleset** is a folder of one or more rule files (``.pdf``/``.md``/``.txt``).
Its **slug** is the identity everything else keys on: citations
(``[ultimate II.B.1]``), per-user ``allowed_domains``, ``eval/gold/<slug>.jsonl``,
the index (``data/index/<slug>/``) and the registry. Two layouts are allowed::

    rules/tennis/                 flat: one edition      -> slug "tennis"
        tennis.md
    rules/ultimate/               a game with editions (holds only folders)
        1990/  -> slug "ultimate_1990"
        2026/  -> slug from its marker (e.g. "ultimate", kept from when it was flat)

Folders say at most "same game". File names carry no meaning and are never
parsed. Everything finer (the edition label, the slug) is data, kept in a
machine-written **marker file** (``.ruleset.json``) in each ruleset folder. A
folder without one gets it on the first build, with the slug derived from the
path (flat ``rules/x/`` -> ``x``; nested ``rules/x/e/`` -> ``x_e``). Once written,
the marker's slug wins over the path, so moving the folder keeps its slug.

Layout rule for a top-level folder that holds BOTH rule files and subfolders
with rule files: its own files are the ruleset (unchanged slug), and the
subfolders are reported and NOT built until the folder is tidied (``rulebook.add
<game> --edition ...`` moves the flat files into a labelled edition folder).
Folders nested deeper than ``rules/<game>/<edition>/`` are reported, not built.

Content hashes (sha256 per file) let the build warn about exact duplicates and
spot a folder that was moved without its marker. They only ever warn and
suggest; nothing is linked, moved or deleted on their say-so.

CLI: ``python -m rulebook.rulesets`` lists rulesets and any layout problems;
``... nest <game> <label>`` moves a flat game's files into an edition folder
(keeping the slug); ``... claim <folder> <slug>`` writes a marker on request
(the fix the moved-folder warning suggests).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

MARKER_NAME = ".ruleset.json"
MARKER_SCHEMA = 1
SOURCE_SUFFIXES = frozenset({".pdf", ".md", ".txt"})
# Same shape `rulebook.add` has always accepted. No "/" ever: citations
# (generate._CITATION_RE) and index dirs need a flat slug.
VALID_SLUG = re.compile(r"[a-z0-9][a-z0-9_-]*")
_NOTE = "Written by rulebook (rulebook.rulesets). Do not edit; it keeps this ruleset's slug when the folder moves."


@dataclass
class Ruleset:
    slug: str
    dir: Path
    files: list[Path]  # ingestable, after the .extracted.md skip
    game: str | None = None
    edition: str | None = None
    marker: dict | None = None  # the marker as read; None if the folder has none
    hashes: dict[Path, str] = field(default_factory=dict)  # filled when hashing

    @property
    def derived_from_path(self) -> bool:
        return self.marker is None


@dataclass
class Issue:
    level: str  # "error" (something is not built) | "warning"
    path: Path
    message: str

    def __str__(self) -> str:
        return f"[{self.level}] {self.path}: {self.message}"


@dataclass
class Discovery:
    rulesets: list[Ruleset]
    issues: list[Issue]

    def by_slug(self) -> dict[str, Ruleset]:
        return {r.slug: r for r in self.rulesets}


# ── Small helpers ─────────────────────────────────────────────────────────


def _visible_dirs(p: Path) -> list[Path]:
    return sorted(d for d in p.iterdir() if d.is_dir() and not d.name.startswith("."))


def _is_rule_file(p: Path) -> bool:
    return p.is_file() and not p.name.startswith(".") and p.suffix.lower() in SOURCE_SUFFIXES


def rule_files(folder: Path) -> list[Path]:
    """Ingestable files directly in ``folder``.

    A ``<stem>.pdf`` with an ``<stem>.extracted.md`` sibling is skipped in favour
    of the transcription (image-only PDFs; see scripts/vision_extract.py).
    """
    files = sorted(p for p in folder.iterdir() if _is_rule_file(p))
    extracted = {p.name.removesuffix(".extracted.md") for p in files if p.name.endswith(".extracted.md")}
    return [p for p in files if not (p.suffix.lower() == ".pdf" and p.stem in extracted)]


def _has_rule_files_below(folder: Path) -> bool:
    return any(_is_rule_file(p) for p in folder.rglob("*"))


def normalize_label(label: str) -> str:
    """A folder name as a slug part: lowercase, runs of other chars -> ``_``."""
    return re.sub(r"[^a-z0-9_-]+", "_", label.lower()).strip("_")


def derived_slug(game: str, edition: str | None = None) -> str:
    """The slug a folder gets when it has no marker (today's rule, extended)."""
    if edition is None:
        return game  # flat: the folder name, unchanged (compatibility)
    return f"{normalize_label(game)}_{normalize_label(edition)}"


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ── Markers ───────────────────────────────────────────────────────────────


def read_marker(folder: Path) -> dict | None:
    """The folder's marker, or None if absent. Raises ValueError if unusable."""
    path = folder / MARKER_NAME
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"unreadable {MARKER_NAME}: {e}") from e
    slug = data.get("slug") if isinstance(data, dict) else None
    if not isinstance(slug, str) or not VALID_SLUG.fullmatch(slug):
        raise ValueError(f"{MARKER_NAME} has no valid slug (got {slug!r})")
    return data


def marker_payload(slug: str, game: str | None = None, edition: str | None = None) -> dict:
    data: dict = {"slug": slug}
    if game:
        data["game"] = game
    if edition:
        data["edition"] = edition
    data["schema"] = MARKER_SCHEMA
    data["_note"] = _NOTE
    return data


def write_marker(folder: Path, slug: str, game: str | None = None, edition: str | None = None) -> Path:
    if not VALID_SLUG.fullmatch(slug):
        raise ValueError(f"invalid slug {slug!r}")
    path = folder / MARKER_NAME
    path.write_text(json.dumps(marker_payload(slug, game, edition), indent=2) + "\n")
    return path


# ── Discovery ─────────────────────────────────────────────────────────────


def discover(
    rules_root: Path,
    *,
    hash_files: bool = False,
    known_hashes: Mapping[str, Iterable[str]] | None = None,
) -> Discovery:
    """Find every ruleset under ``rules_root`` and resolve its slug. Read-only.

    ``hash_files`` fills ``Ruleset.hashes`` and adds duplicate-content warnings.
    ``known_hashes`` ({slug: sha256s} from previous builds' manifests) turns on
    moved-folder detection: a marker-less folder whose files match a built slug
    whose folder is gone is held back (not returned) with a suggestion.
    """
    issues: list[Issue] = []
    found: list[tuple[Path, str | None, str | None]] = []  # (dir, game, edition)

    for top in _visible_dirs(rules_root):
        own = rule_files(top)
        subs = [d for d in _visible_dirs(top) if _has_rule_files_below(d)]
        if own:
            found.append((top, None, None))
            for s in subs:
                issues.append(Issue("error", s, (
                    f"not built: {top.name}/ holds its own rule files AND edition "
                    f"folders. Its own files stay the ruleset; move them into a "
                    f"labelled edition folder (keeping their slug) with "
                    f"`python -m rulebook.rulesets nest {top.name} <label>` to build this one."
                )))
            continue
        if not subs:
            # No rule files anywhere below: not a ruleset. Only a leftover marker is worth a word.
            if (top / MARKER_NAME).exists():
                issues.append(_orphan_marker(top))
            continue
        if (top / MARKER_NAME).exists():
            issues.append(Issue("warning", top / MARKER_NAME, (
                "a game folder (only edition folders inside) holds a ruleset marker. "
                "It was probably left behind when its files moved into an edition "
                "folder; move it into that folder to keep the slug."
            )))
        for d in _visible_dirs(top):
            if d not in subs and (d / MARKER_NAME).exists():
                issues.append(_orphan_marker(d))  # an edition folder emptied of its files
        for s in subs:
            for deeper in (d for d in _visible_dirs(s) if _has_rule_files_below(d)):
                issues.append(Issue("error", deeper, (
                    f"not built: rulesets nest at most one level (rules/{top.name}/<edition>/)."
                )))
            if rule_files(s):
                found.append((s, top.name, s.name))

    rulesets: list[Ruleset] = []
    for folder, game, edition in found:
        try:
            marker = read_marker(folder)
        except ValueError as e:
            issues.append(Issue("error", folder / MARKER_NAME, f"not built: {e}"))
            continue
        if marker is not None:
            slug = marker["slug"]
            if game is None:  # flat: the marker may carry an edition label (rulebook.add)
                game, edition = marker.get("game"), marker.get("edition")
        else:
            slug = derived_slug(game or folder.name, edition)
            if not VALID_SLUG.fullmatch(slug):
                issues.append(Issue("error", folder, (
                    f"not built: folder name gives slug {slug!r}, which is not a valid "
                    "slug (lowercase letters, digits, '-', '_'). Rename the folder."
                )))
                continue
        rulesets.append(Ruleset(slug, folder, rule_files(folder), game, edition, marker))

    # Two folders, one slug: refuse both rather than guess which one is real.
    by_slug: dict[str, list[Ruleset]] = defaultdict(list)
    for r in rulesets:
        by_slug[r.slug].append(r)
    clashing = {s for s, rs in by_slug.items() if len(rs) > 1}
    for s in sorted(clashing):
        dirs = ", ".join(str(r.dir) for r in by_slug[s])
        for r in by_slug[s]:
            issues.append(Issue("error", r.dir, f"not built: slug {s!r} is claimed by several folders ({dirs})."))
    rulesets = [r for r in rulesets if r.slug not in clashing]

    if hash_files or known_hashes is not None:
        for r in rulesets:
            r.hashes = {p: file_sha256(p) for p in r.files}
        issues.extend(_duplicate_issues(rulesets))
    if known_hashes is not None:
        rulesets, moved = _hold_back_moved(rulesets, known_hashes)
        issues.extend(moved)

    return Discovery(rulesets, issues)


def _orphan_marker(folder: Path) -> Issue:
    """A folder holding a ruleset marker but no rule files: its files moved away."""
    try:
        slug = (read_marker(folder) or {}).get("slug")
    except ValueError:
        slug = None
    named = f" for slug {slug!r}" if slug else ""
    return Issue("warning", folder / MARKER_NAME, (
        f"holds a ruleset marker{named} but no rule files, so its files were probably "
        f"moved out. If they moved, `python -m rulebook.rulesets claim <their folder> "
        f"{slug or '<slug>'}` keeps the slug; otherwise remove this folder."
    ))


def _duplicate_issues(rulesets: list[Ruleset]) -> list[Issue]:
    seen: dict[str, list[tuple[Ruleset, Path]]] = defaultdict(list)
    for r in rulesets:
        for p, h in r.hashes.items():
            seen[h].append((r, p))
    issues = []
    for h, hits in seen.items():
        if len(hits) < 2:
            continue
        where = ", ".join(f"{p} ({r.slug})" for r, p in hits)
        issues.append(Issue("warning", hits[0][1], (
            f"identical content (sha256 {h[:12]}) in {where}. Both are built; if "
            "one is an accidental copy, remove it yourself."
        )))
    return issues


def _hold_back_moved(
    rulesets: list[Ruleset], known_hashes: Mapping[str, Iterable[str]]
) -> tuple[list[Ruleset], list[Issue]]:
    """Hold back a marker-less folder whose files match a built-but-vanished slug."""
    present = {r.slug for r in rulesets}
    orphans = {s: set(hs) for s, hs in known_hashes.items() if s not in present and hs}
    kept, issues = [], []
    for r in rulesets:
        if r.marker is not None or r.slug in known_hashes or not r.hashes:
            kept.append(r)
            continue
        mine = set(r.hashes.values())
        best = max(orphans, key=lambda s: len(mine & orphans[s]), default=None)
        if best is None or not mine & orphans[best]:
            kept.append(r)
            continue
        issues.append(Issue("error", r.dir, (
            f"not built: its files match ruleset {best!r}, whose folder is gone, so it "
            f"looks moved without its {MARKER_NAME}. To keep the slug: "
            f"`python -m rulebook.rulesets claim {r.dir} {best}`. To make it a new "
            f"ruleset instead: `python -m rulebook.rulesets claim {r.dir} {r.slug}`."
        )))
    return kept, issues


def ensure_markers(discovery: Discovery) -> list[Path]:
    """Write or refresh each discovered ruleset's marker; returns paths written.

    A missing marker gets the path-derived slug. An existing marker keeps its
    slug; only a nested folder's ``game``/``edition`` are refreshed from its
    location (they describe where it is now). Unchanged markers aren't touched.
    """
    written = []
    for r in discovery.rulesets:
        want = marker_payload(r.slug, r.game, r.edition)
        have = r.marker or {}
        if all(have.get(k) == want.get(k) for k in ("slug", "game", "edition")):
            continue
        written.append(write_marker(r.dir, r.slug, r.game, r.edition))
        r.marker = want
    return written


def nest_flat(rules_root: Path, game: str, label: str) -> Path:
    """Move a flat game's own files into ``rules/<game>/<label>/``, keeping its slug.

    The marker is written (path-derived slug) BEFORE anything moves, then moves
    with the files, so identity survives. Edition folders already inside (the
    mixed layout) stay put. Everything else moves: nothing is deleted. Returns
    the new edition folder.
    """
    top = rules_root / game
    if not top.is_dir() or not rule_files(top):
        raise ValueError(f"{top} is not a flat ruleset (no rule files directly inside)")
    if not label or label.startswith(".") or "/" in label or label != label.strip():
        raise ValueError(f"invalid edition label {label!r}")
    dest = top / label
    if dest.exists():
        raise ValueError(f"{dest} already exists; pick another label for the existing files")
    marker = read_marker(top)
    slug = marker["slug"] if marker else derived_slug(game)
    write_marker(top, slug)  # pin identity before the move
    editions = {d for d in _visible_dirs(top) if _has_rule_files_below(d)}
    movers = [p for p in top.iterdir() if p not in editions]
    dest.mkdir()
    for p in movers:
        p.rename(dest / p.name)
    write_marker(dest, slug, game, label)
    return dest


def ruleset_meta(rules_root: Path) -> dict[str, tuple[str | None, str | None]]:
    """{slug: (game, edition)} for labels. Read-only; {} if the root is missing."""
    if not rules_root.is_dir():
        return {}
    return {r.slug: (r.game, r.edition) for r in discover(rules_root).rulesets}


def find_ruleset(rules_root: Path, slug: str) -> Ruleset | None:
    return discover(rules_root).by_slug().get(slug)


# ── CLI ───────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    from .config import settings

    parser = argparse.ArgumentParser(prog="python -m rulebook.rulesets", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd")
    claim = sub.add_parser("claim", help="write a folder's marker with the given slug")
    claim.add_argument("folder", type=Path)
    claim.add_argument("slug")
    nest = sub.add_parser("nest", help="move a flat game's files into an edition folder, keeping the slug")
    nest.add_argument("game")
    nest.add_argument("label", help="edition label for the existing files, e.g. 2026")
    args = parser.parse_args(argv)
    root = settings.rules_dir

    if args.cmd == "claim":
        folder = args.folder.resolve()
        if not folder.is_dir() or not rule_files(folder):
            print(f"error: {folder} is not a folder of rule files.", file=sys.stderr)
            return 2
        if not VALID_SLUG.fullmatch(args.slug):
            print(f"error: {args.slug!r} is not a valid slug.", file=sys.stderr)
            return 2
        other = find_ruleset(root, args.slug)
        if other is not None and other.dir.resolve() != folder:
            print(f"error: {args.slug!r} already belongs to {other.dir}.", file=sys.stderr)
            return 2
        nested = folder.parent.resolve() != root.resolve()
        game, edition = (folder.parent.name, folder.name) if nested else (None, None)
        print(f"wrote {write_marker(folder, args.slug, game, edition)}")
        return 0

    if args.cmd == "nest":
        try:
            dest = nest_flat(root, args.game, args.label)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        print(f"moved {args.game}'s files into {dest} (slug unchanged)")
        return 0

    d = discover(root, hash_files=True)
    for r in d.rulesets:
        label = f"{r.game} / {r.edition}" if r.edition else (r.game or "")
        origin = "path" if r.derived_from_path else "marker"
        print(f"{r.slug:<24} {len(r.files):>3} file(s)  {label:<24} slug from {origin}  {r.dir}")
    for issue in d.issues:
        print(issue)
    return 1 if any(i.level == "error" for i in d.issues) else 0


if __name__ == "__main__":
    raise SystemExit(main())
