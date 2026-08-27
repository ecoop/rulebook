# Adding sources from the UI — scoping

_Last updated: 2026-08-27_

> **Status: scoping, not scheduled.** Answers "what would it take to add Sources from
> the UI?" This is a **new feature**, not a permission tweak — the Sources tab today
> only *toggles* files that already exist on disk. Ties into
> [`rbac-capabilities.md`](rbac-capabilities.md) via the `sources.add` capability.

## How sources work today

- Sources are files under `rules/<domain>/` — `.pdf`, `.md`, `.txt`
  (`scripts/build_index.py:_SOURCE_SUFFIXES`).
- `discover_sources(rules_root)` walks that tree at **build time**; every file becomes
  a `Source`, minus anything the admin excluded via `source_curation.jsonl`.
  `settings.rules_dir` resolves to `repo_root/rules` in dev; on a hosted (gcs)
  deploy it's a writable dir under `data_dir` that `rules_sync` populates from the
  bucket's `rules/` prefix at runtime (#170) — the image no longer bakes `rules/` in.
- The Sources tab (`GET /advanced/sources`) lists those files and lets an admin toggle
  *Incl.* It **cannot add a file** — new sources appear only by dropping a file into
  `rules/<domain>/` in the repo and rebuilding.
- Rebuild reads sources from disk, embeds, writes the index (to GCS on the hosted
  deploy via `index_sync`).

## The core obstacle: the hosted filesystem is read-only + ephemeral

On Cloud Run the writable area is `/tmp` (wiped per instance), so an upload endpoint
can't durably write into `rules_dir`. **Most of the durable home already exists:** as
of #170 the rule docs live in `gs://<bucket>/rules/<domain>/…` and `rules_sync` pulls
them into the writable `rules_dir` on boot and before a rebuild (mirroring `index_sync`
/ `log_sync`). What's left for UI-added sources is the *write* path (an upload endpoint)
plus surfacing it — the read/sync plumbing is done.

## What it takes

1. **Write uploads to the existing GCS `rules/` prefix.** An upload endpoint writes the
   bytes to `gs://<bucket>/rules/<domain>/<name>` — the same prefix `rules_sync` already
   reads — so `discover_sources` picks them up on the next sync + rebuild. (No new
   `sources/` prefix needed; reuse `rules/`.)

2. **Upload endpoint** — `POST /advanced/sources` (multipart: file + `domain`), gated by the
   new `sources.add` capability. It must:
   - **validate type** against `_SOURCE_SUFFIXES` (`.pdf`/`.md`/`.txt` only — no
     arbitrary uploads),
   - **cap size** (say a few MB) and sanitize the filename (no path traversal; slug the
     stem),
   - **reject or version duplicates** (same `domain/name`),
   - write the bytes to `gs://…/sources/<domain>/<name>`,
   - return the new `AdminSourceRow` so the tab updates.

3. **Rebuild reads the union.** `admin_rebuild_index` already shells `build_index.py`;
   ensure the GCS sources are synced into `rules_dir` first so `discover_sources` picks
   them up. A freshly-uploaded file is **included by default** (absent from
   `source_curation` = included), so it flows into the next rebuild automatically — same
   rule as today.

4. **Ingest handles the new file.** `.md`/`.txt` are trivial. **PDFs are the sharp
   edge**: image-only PDFs produce nothing from `pypdf` and today rely on a
   pre-computed `*.extracted.md` sibling from `vision_extract.py`. An uploaded scanned
   PDF would either need that extraction run server-side (a heavier, slower, cost-
   bearing step) or be rejected with a clear "text-only PDFs; run extraction locally
   first" message. **Recommend: v1 accepts text-extractable PDFs + md/txt, and rejects
   image-only PDFs** rather than building the vision pipeline into the request path.

5. **UI.** An upload control on the Sources tab (domain picker + drag-drop), shown only
   with `sources.add`, plus a "rebuild needed to take effect" hint — uploading stages a
   file; the *Rebuild Index* button is still what puts it in the index.

## Gotchas

- **Rebuild is still required** — upload ≠ searchable. Make that obvious in the UI so it
  doesn't read as a no-op.
- **Security** — restrict to the three suffixes, size-cap, sanitize names; never execute
  or trust uploaded content. Files are retrieved into prompts, so treat their text as
  untrusted (it already is, for baked-in sources).
- **Cost/footprint** — durable GCS storage + a rebuild per batch; fine at demo scale.
- **Delete/replace** — out of scope for v1; `source_curation` already lets you *exclude*
  an uploaded file, which covers "oops, wrong file" without a hard delete.

## Suggested phasing

1. **GCS-backed sources** (sync-in + `sources.add` capability wired, no UI) — the
   plumbing, testable via the endpoint.
2. **Upload endpoint** with validation + dedup.
3. **UI control** on the Sources tab (after the `AdminApp.tsx` RBAC/sorting/rename work
   lands — same-file collision as everything else on that tab).
4. *(maybe)* server-side vision extraction for image-only PDFs — only if a real source
   needs it.
