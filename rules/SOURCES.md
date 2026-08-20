<!-- Copyright (c) 2026 Eric Cooper. -->
# Rules sources — point-and-download

_Last updated: 2026-08-19_

The rules text under `rules/<domain>/` is built into the vector index by
[`scripts/build_index.py`](../scripts/build_index.py) (the directory name is the
domain slug; discovery is data-driven — no code change to add a domain). Each
source document is published by its sport's governing body and is **copyrighted**;
this file records **where to download each one** so a fresh checkout can rebuild
the index without the binaries living in git.

> **Do not commit copyrighted source PDFs.** Download them into the domain's
> directory locally, build the index, and publish the built index to GCS. The
> `.extracted.md` transcriptions and the built index — not the source PDFs — are
> what the running service needs. (Existing committed PDFs are being migrated to
> this model; see the go-public cleanup.)

## Domains

### ultimate — Ultimate (USA Ultimate)
- **Official Rules of Ultimate**, USA Ultimate. → `rules/ultimate/2026-27-Official-Rules-of-Ultimate.pdf`
  URL: https://usaultimate.org/rules/ ‹confirm exact PDF link for the 2026-27 edition›
- **10 Simple Rules**, USA Ultimate. → `rules/ultimate/10SimpleRules.pdf`
  URL: https://usaultimate.org/ ‹confirm exact link›

### goaltimate — Goaltimate (USAG)
- **Goaltimate field setup / regulations (2017)**. → `rules/goaltimate/goaltimate-field-setupregulation2017.pdf`
  (+ `…​.extracted.md` transcription) — URL: ‹confirm official USAG source›
- **USAG rules v2.1.3**. → `rules/goaltimate/usag-rule-v-2-1-3.pdf` — URL: ‹confirm›
- **USAG field diagram**. → `rules/goaltimate/usag-field-diagram.pdf` (+ `.extracted.md`) — URL: ‹confirm›

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
