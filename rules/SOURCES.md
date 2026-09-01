<!-- Copyright (c) 2026 Eric Cooper. -->
# Rules sources — point-and-download

_Last updated: 2026-08-31_

The rules text under `rules/<domain>/` is built into the vector index by
[`scripts/build_index.py`](../scripts/build_index.py) (the directory name is the
domain slug; discovery is data-driven — no code change to add a domain). This
file records **where to download each source document** so a fresh checkout can
rebuild the index.

> **Copyright.** Each source document is a third-party work published by its
> governing body or publisher and is **copyrighted**. This project **links to
> the official sources and does not redistribute them** — download each one
> yourself, for your own use, under the publisher's terms. Nothing copyrighted
> lives in git: not the source PDFs, not the `.extracted.md` transcriptions, and
> not the built index (`chunks.jsonl` holds verbatim rule text). All three are
> gitignored and produced locally; a hosted instance syncs them privately from
> its own storage.

## Reproduce the shipped domains (quickstart)

To rebuild the index for the four sport domains this project ships —
**ultimate, goaltimate, badminton, curling** — download each document from its
official source (linked per-domain under [Domains](#domains) below) into the
matching `rules/<domain>/` directory, then build:

```
mkdir -p rules/ultimate rules/goaltimate rules/badminton rules/curling
# Download each PDF from the official URLs below into its dir, e.g.
#   rules/ultimate/2026-27-Official-Rules-of-Ultimate.pdf
# (image-only PDFs — e.g. the goaltimate diagrams — transcribe first;
#  see step 2 of "Adding a domain" below.)

uv run python scripts/build_index.py    # discovers rules/<domain>/, builds data/index/
```

Downloads are **manual by design**: you accept each publisher's terms, and some
sites (e.g. BWF) block automated fetchers. No downloader/scraper ships with this
repo.

## Domains

### ultimate — Ultimate (USA Ultimate)
- **Official Rules of Ultimate**, USA Ultimate. → `rules/ultimate/2026-27-Official-Rules-of-Ultimate.pdf`
  URL: https://usaultimate.org/rules/ (HTML + PDF hub); direct PDF:
  https://usaultimate.org/wp-content/uploads/2025/12/2026-27-Official-Rules-of-Ultimate.pdf
- **10 Simple Rules**, USA Ultimate. → `rules/ultimate/10SimpleRules.pdf`
  URL: https://usaultimate.org/rules/ (linked from the Rules hub)

### goaltimate — Goaltimate (USAG)
- **Goaltimate field setup / regulations (2017)**. → `rules/goaltimate/goaltimate-field-setupregulation2017.pdf`
  (+ `…​.extracted.md` transcription) — URL: https://www.usagoaltimate.org/rules (Rules hub)
- **USAG rules v2.1.3**. → `rules/goaltimate/usag-rule-v-2-1-3.pdf` — direct PDF:
  https://d36m266ykvepgv.cloudfront.net/uploads/media/XhCa3uWktp/o/usag-rule-v-2-1-3.pdf
  (linked from https://www.usagoaltimate.org/rules)
- **USAG field diagram**. → `rules/goaltimate/usag-field-diagram.pdf` (+ `.extracted.md`) — URL: https://www.usagoaltimate.org/rules

### badminton — Badminton (BWF)  _(#114 — pending download)_
- **Laws of Badminton** — BWF Statutes, Section 4.1. **Version 4.0, in force
  05/08/2024** (the edition governing play now). → download into
  `rules/badminton/` (suggested: `bwf-laws-of-badminton-v4.0-2024.pdf`).
  Listed at https://corporate.bwfbadminton.com/statutes/ (Chapter 4); direct PDF:
  https://system.bwfbadminton.com/documents/folder_1_81/Statutes/CHAPTER-4---RULES-OF-THE-GAME/SECTION%204.1-%20Laws%20of%20Badminton.pdf
  (opens in a browser; 403s automated fetchers).
  - **Scheduled swap:** a new edition (3×4 scoring — Clauses 7/8/16, adopted at
    BWF AGM Apr 2026) comes **into force 4 January 2027**; re-ingest then.
  - **Do NOT ingest** BWF §4.1.4 *Alternative Laws of Badminton* (half-court and
    other variants) as default rules — variant handling is tracked in #120.

### curling — Curling (World Curling)  _(#114 — pending download)_
- **The Rules of Curling (2025)** — World Curling, the current edition.
  → download into `rules/curling/` (suggested: `wcf-rules-of-curling-2025.pdf`).
  Listed at https://worldcurling.org/rules/ ; direct PDF:
  https://worldcurling.org/wp-content/uploads/2025/08/Rules-2025.pdf
  - Optional companions (not the core rules): *Competition Policy & Procedure
    Manual (19 Aug 2025)* for competition procedures; *Rules of Curling Showing
    Changes (2025)* is just a diff — don't ingest it.

### hearts — Hearts  _(#142)_
- **Hearts rules** — Wikibooks, "Card Games/Hearts/Rules"
  (https://en.wikibooks.org/wiki/Card_Games/Hearts/Rules), **CC BY-SA 4.0**. Kept
  **untracked** in `rules/hearts/` for consistency with the other sources.
  → `rules/hearts/rules-for-hearts.pdf`
  - Ingestion reads a cleaned transcription sibling
    `rules-for-hearts.extracted.md` (also untracked): the PDF's multi-column print
    scrambled the layout (section headings detached from their bodies; the
    player-count comparison table flattened to number-soup), so the extraction was
    reordered back onto its headings, the table rebuilt as markdown, wiki chrome
    (retrieval URL, floating labels) dropped, and ligatures normalized.
  - CC BY-SA permits committing *with attribution* if we ever want to; left
    untracked for now to match the rest.

### backgammon — Backgammon (USBGF)  _(#142)_
- **Backgammon rules** — U.S. Backgammon Federation, "Backgammon Basics: How To
  Play" (https://usbgf.org/backgammon-basics-how-to-play/). **Copyrighted** —
  download into `rules/backgammon/` and keep it **untracked** (like the sport
  rulebooks). → `rules/backgammon/backgammon-rules.pdf`
  - Ingestion reads a cleaned transcription sibling
    `backgammon-rules.extracted.md` (also **untracked**): the FAQ ("Common
    Questions") onward trimmed off; print-capture cruft (language-link sidebar,
    a browser-extension ad) and figure captions removed; PDF ligatures
    normalized; the document's own section headings kept as `##` for
    section-based chunking. The `.extracted.md` makes ingestion skip the `.pdf`
    automatically (`<stem>.pdf` + `<stem>.extracted.md` → pdf skipped).

> **Source policy.** Governing-body / publisher rulebooks (ultimate, goaltimate,
> badminton, curling, and backgammon) are **copyrighted**
> — point-and-download, never committed; a cleaned `.extracted.md` transcription
> (also untracked) is what ingestion reads. Hearts uses a CC BY-SA Wikibooks
> source, likewise kept untracked for consistency. Both game domains began as
> committed original drafts, then were swapped for sourced text for fidelity.

## Adding a domain (runbook)

1. **Create the dir and download the doc(s)** (do not commit the copyrighted PDF):
   ```
   mkdir -p rules/badminton
   # download the BWF Laws of Badminton PDF into rules/badminton/
   ```
2. **(If the PDF is image-only / extracts as one word per line)** transcribe it
   with vision, producing a `.extracted.md` sibling that ingestion prefers over
   the PDF:
   ```
   uv run python scripts/vision_extract.py rules/badminton/laws-of-badminton.pdf
   ```
3. **Add this file's source entry** above (governing body, document, URL, local path).
4. **Rebuild the index** — discovery picks up the new dir automatically:
   ```
   uv run python scripts/build_index.py
   ```
5. **Register the domain** (display name, source URL(s); enabled by default):
   ```
   uv run python -m scripts.domains set badminton --name "Badminton (BWF)" \
       --sources https://bwfbadminton.com/...
   ```
6. **Publish the built index to GCS** so hosted instances pick it up
   (`index_sync.publish_index_to_gcs`, or the Rebuild-index admin action from a
   build that has the docs), then deploy if needed.
7. **Grant access** — new domains reach no one until granted (the #112 policy):
   grant via the Users tab or `uv run python -m scripts.allowed_domains set <token> --domains ultimate,goaltimate,badminton`.
