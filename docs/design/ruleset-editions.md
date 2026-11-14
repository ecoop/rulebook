<!-- Copyright (c) 2026 Eric Cooper. -->
# Ruleset editions

_Last updated: 2026-11-13_

Rulebook can hold several editions or sources of one game, such as Ultimate's
1990 and 2026 rules, or the bundled tennis sample beside the official ITF rules.
It tells a deliberate second edition from an accidental duplicate. Implementation:
[`src/rulebook/rulesets.py`](../../src/rulebook/rulesets.py).

## Rules

- **A ruleset is a folder of one or more rule files** (`.pdf`/`.md`/`.txt`),
  never a single file.
- **File names carry no meaning.** Publisher PDFs keep their long names; nothing
  parses them for a game or edition.
- **Folders say at most "same game".** A one-edition game stays flat
  (`rules/ultimate/`). A game with editions holds only edition folders
  (`rules/ultimate/1990/`, `rules/ultimate/2026/`). Nesting stops there.
- **Everything finer is data**, kept in a machine-written marker,
  `.ruleset.json`, in each ruleset folder: `slug`, plus `game` and `edition`
  when known. People never edit it.
- **The slug is the identity.** Citations (`[ultimate II.B.1]`), each user's
  `allowed_domains`, `eval/gold/<slug>.jsonl`, the index (`data/index/<slug>/`,
  `gs://…/index/<slug>/`) and the registry all key on it. Slugs stay flat (no
  `/`), so `_CITATION_RE` is unchanged.
- **First build writes the marker from the path:** `rules/ultimate/` gives
  `ultimate` (today's rule, so existing rulesets need no migration), and
  `rules/ultimate/1990/` gives `ultimate_1990`. **After that the marker's slug
  wins over the path**, so a moved folder keeps its slug. The build refreshes a
  nested marker's `game`/`edition` to match where the folder now is, and never
  its slug.
- **Declaring a sibling is low effort:**
  `python -m rulebook.add ultimate 1990 <file>` (or `--edition 1990`). If the
  game is flat, `add` first moves its files into a labelled edition folder
  (`--existing-edition`, the label recorded when it was added, or a prompt). It
  writes their marker before the move, so they keep the slug `ultimate`. The new
  files get `ultimate_1990`. `python -m rulebook.rulesets nest ultimate 2026`
  does only the move. Nothing is deleted.

## A folder with both files and edition folders

Its own files remain the ruleset, with its slug unchanged. Each subfolder holding
rule files is reported as an error and **not built** until the folder is tidied
with `rulebook.rulesets nest <game> <label>`. This happens when someone drops
`1990/` beside an existing flat game. Building the subfolder anyway could turn a
stray `appendix/` into a new, visible ruleset, and today's builder already
ignores subfolders. The difference is that the mixed folder is now reported
instead of skipped silently. A folder nested deeper than `<game>/<edition>/`,
an unreadable marker, or two folders claiming one slug are reported the same
way and not built.

## Content hashes

Each build records a sha256 for every source file in the index manifest
(`sources[].sha256`, beside `path`, `game`, `edition`). The next build uses them to:

- **warn about exact duplicates** across or within rulesets. Both copies are
  still built; removing one is the user's decision.
- **spot a folder moved without its marker**, for example after
  `mv ultimate/* ultimate/2026/`, since `*` skips dotfiles. If a folder has no
  marker and its files match a built slug whose folder is gone, it is held back.
  It gets no marker and no build, and the report suggests
  `python -m rulebook.rulesets claim <folder> <slug>` to keep the old slug, or
  the derived slug to make it new. A marker left on the now-game folder is
  reported too.

Hashes only warn and suggest. Nothing is linked, moved or deleted on their say-so.
Indexes built before this change have no hashes, so detection starts after one
rebuild.

## Default edition when a question names only the game

Not built yet. Proposed rule: the registry may declare a game's default edition.
Otherwise it is the edition whose label sorts last (natural sort, so `2026` beats
`1990`). A flat game is its own default. The picker keeps listing every edition
as its own domain, labelled "Ultimate (1990)". The default only matters where a
caller names a game rather than slugs, such as a future `--domain ultimate` that
falls through to `ultimate_<default>`, or a game-level grant.

## "What changed between editions" (cross-domain mode)

Editions are ordinary domains, so cross-domain mode already works: select
`ultimate` and `ultimate_1990`, and the prompt names them by their labels, e.g.
"Ultimate (2026)" and "Ultimate (1990)" (an explicit registry `display_name`
still wins). It already tells the model to "structure your answer by
domain so the differences are obvious". A dedicated "compare editions" framing
could go further: retrieve the same top-k per edition for the same question,
pair passages by rule number when the numbering carries over, and ask for
"unchanged / changed / new / removed".

## Sync, samples, and git

- **GCS sync.** The pull mirrors every object path, so nested folders and
  markers arrive intact. The push (`publish_rules`) now uploads `.ruleset.json`
  too. Publishing never deletes, so after nesting a game the old flat objects
  linger and would sync back as a mixed folder. `publish_rules` lists them,
  and removing them is the operator's call. The operator's local `rules/` is
  the source of truth. A marker the container writes in its sync dir is lost
  on restart, which is harmless because it holds only a path-derived slug.
- **Samples.** The markers for `checkers`, `tennis` and `poker` are committed.
  Without them, a fresh clone's first build would leave three untracked files.
  They also pin slugs that tests, eval and the notebooks rely on, and show users
  what a marker looks like. Markers in your own rulesets are gitignored, like
  the PDFs beside them.
- **Curation keys are paths** (`rules/<game>/<edition>/<file>`), so moving a file
  resets its include/exclude state. The admin scope check now maps a path to its
  slug through discovery.

## Later

- The default-edition rule above, and game-level grants.
- A compare-editions mode.
- Show `game`/`edition` in the Indices and Sources tabs (`DomainInfo` has them).
- Carry curation state across a move by keying on content hash.
- Optional `publish_rules --prune` (with confirmation) for the stale objects it
  now only lists.
