# Design study — rulesets, multi-select, and per-user access

_Last updated: 2026-08-18_

Status: **design / not yet built.** Targets the **Version 1.1** milestone. Decision-oriented —
options and recommendations, for Eric to choose the path. Grounded in the code as of build 107.

## Summary

Three connected features, plus a framing shift:

1. **Add rulesets** (badminton, curling — and, more importantly, non-sports domains).
2. **Multi-select** the rulesets a question runs against (arbitrary subset, not just All/A/B).
3. **Per-user ruleset access** — constrain which rulesets a user can ask about *and* view.

Framing shift: a "sport" is already just a tagged corpus. The architecture is domain-agnostic,
so 1.1 is the moment to think of these as **rulesets / domains**, not "sports" — board games,
tabletop RPGs, legal codes, HR policies, API docs, anything with cited answers over a ruleset.

## Current model (anchors)

- **A "sport" is a directory name discovered at build time**, not a declared enum:
  `discover_sources()` walks `rules/<sport>/` (`scripts/build_index.py`, `sport = sport_dir.name`).
  The *served* list comes from the index manifest (`store.py list_sports()` → `GET /meta` →
  the frontend picker, `web/src/App.tsx`).
- **But there is a hardcoded second copy:** `DEFAULT_SPORTS = ["ultimate", "goaltimate"]`
  (`pipeline.py`). It's the "known sports" set that gold `## Sport` heading-splitting validates
  against (`build_index.py`) and the cross-sport fallback. **Drift fails silently** — a gold
  written `## Badminton …` is dropped until this constant includes badminton.
- **One index, all sports.** `vectors.npy` + `chunks.jsonl` + `manifest.json` in one dir; each
  chunk row carries a `sport`. Rebuilt globally by `POST /advanced/rebuild-index`; synced to/from
  GCS. `retrieve_across_sports()` does top-k **per sport** and concatenates.
- **`/ask` is single-string-or-null.** `AskRequest.sport: str | None`. `ask()` already accepts a
  `sports: list[str]` kwarg, but no caller passes one.
- **Data model is keyed by id, not sport.** `qa_log` carries the request `sport` (null for
  cross-sport asks); `feedback` has no sport (join via `qa_id → qa_log`); `gold` has no sport
  (derived at build time from `## Sport` headings; a heading-less gold is indexed **once per
  sport** — intrinsically multi-sport). Advanced endpoints filter by author only, never sport.
- **RBAC is capability-based**, 8 cumulative levels, with an orthogonal self/`.all` scope axis.
  **There is no per-user *data-subset* axis today** — every axis is "how much can you do," not
  "which slice of content."
- The only genuine per-sport hardcodes: `DEFAULT_SPORTS` and one line of the system prompt
  ("disc sports (ultimate, goaltimate)", `generate.py`).

## Area 1 — adding rulesets

The architecture is ~80% data-driven already. Adding `badminton`/`curling`: create the dir,
point-and-download the (copyrighted) docs into it, register the source, rebuild. Two hazards:

- **The `DEFAULT_SPORTS` split-brain** — the real sport set is data (manifest) but this constant
  is a second copy whose drift silently drops golds and cross-sport coverage.
- On hosted prod, "add a ruleset" is gated by the same GCS-sources plumbing that `sources.add`
  (see `docs/sources-upload.md`) would provide — not yet built.

**Options:**
- **1a (do now, cheap):** derive the ruleset set from the index (`list_sports`) instead of the
  hardcode; keep a tiny bootstrap constant only for the no-index case. Kills the split-brain in
  ~a dozen lines, no migration.
- **1b (later):** a first-class **ruleset registry** (a `rulesets.json` GCS object, same
  read-with-TTL pattern as roles/tokens) declaring each: slug, display name, source-pointer
  URL(s) for point-and-download, optional numbering-style hint, enabled flag. This is the natural
  home for the copyrighted-doc *pointers* and the generalization beyond sports; pairs with
  `sources.add`.

**Recommendation:** 1a now; 1b when rulesets become a managed, growing/non-sport set.

## Area 2 — multi-select rulesets

The retrieval layer already supports an arbitrary subset (`ask(sports=[...])`); the gap is only
the wire format and the picker.

- **API:** add `sports: list[str] | None` to `AskRequest`. Precedence: non-empty `sports` →
  cross that subset; else singular `sport` (back-compat alias); else all allowed. Forward into
  `ask()`. **Backward compatible.**
- **Token/cost refinement (important as domains grow):** cross-domain retrieval today is
  `k` *per* domain, concatenated — so N domains → N×k passages → N× the generation context.
  Switch to a **global top-k budget** (cap total passages across the union, chosen by relevance)
  so context/cost stays flat as rulesets multiply. See the token note below.
- **Logging:** widen `qa_log` to store `sports: list` (schema bump, additive) so each question
  has an exact ruleset set — this is also what Area 3 needs for precise filtering.
- **Frontend:** replace the `<select>` with a checkbox group over `meta.sports` + an "All"
  affordance. Empty = all.

**Recommendation:** cheapest of the three, mostly additive. Do it early — it's effectively a
prerequisite for Area 3's precision.

## Area 3 — per-user ruleset access

Requirement: a per-user **ruleset allowlist** that constrains both *asking* and *viewing*
(answers, passages, feedback, golds, questions, sources, curation, attribution).

**Model it as a data-scope axis, like self/`.all` — not as capabilities.**
- **3a (recommended):** a **per-token ruleset allowlist**, resolved beside the role from a GCS
  object with the same append-only + TTL pattern as `roles.jsonl`. Sentinel `*`/empty = all (the
  default → nothing changes for existing users). `/me` returns `allowed_rulesets`; every surface
  filters against it. Reuses existing machinery; keeps *assignment* (token→role) and *scope*
  (token→rulesets) as two small independent maps.
- **3b (rejected):** capability-per-ruleset (`ruleset.view:<slug>`) — explodes the closed
  capability set and entangles a *data* axis into the *privilege* ladder.
- **3c (deferred):** groups/teams — an explicit non-goal today.

Sport-scope is an **AND filter applied *after* the capability and self/all checks** — it never
grants, only restricts; fails closed to the configured default (recommend default-**open** for
continuity).

**Enforcement seam (small, since everything carries or joins to a sport):**
- `/ask` + retrieval: intersect requested rulesets with the caller's allowed set; never call the
  unmasked `sport=None` search path for a scoped user (**the one true leak footgun** —
  `store.py`).
- `/advanced/questions`: filter by sport (needs the Area-2 `qa_log.sports` widening; legacy
  null-sport rows need a derivation rule).
- `/advanced/feedback`: join `qa_id → qa_log` for sport.
- `/advanced/golds`: derive the gold's sports from `## Sport` headings (persist a derived
  `sports` field on the row to avoid re-parsing; heading-less = all-sports).
- `/advanced/sources` + curation: sources already carry sport; filter list + reject
  out-of-scope curation writes.
- `/meta` + `/diagnostics`: filter `sports`/`chunks_by_sport` to the caller's allowed set (else
  a badminton-only user learns ultimate exists and its size).
- Audit tab: either tag audit rows with sport and filter, or keep it whole-system behind an
  unscoped operator capability — decide explicitly.

## The index / rebuild decision (the messy part)

Introducing per-user visibility forces a call on what the index *is* and who may rebuild it.

- **Option A (recommended): one index, filter at serve time.** The store already masks by sport;
  scoping is "constrain the sport argument." Cheapest; same UX (comparisons included). Downside:
  isolation is enforced at the query boundary, so a missed codepath leaks — acceptable because
  **published rules are not secrets** (the sensitivity is scoping *views*, not hiding content).
- **Option B (later): per-ruleset indices.** Physical isolation (a badminton-only server never
  loads ultimate vectors) + independent per-ruleset rebuilds. Costs real plumbing (multi-store
  retrieval, per-sport gold partitioning, N manifests) and a migration. Reach for it only when
  you need hard isolation or rebuilds get heavy. **Not a one-way door** — every chunk is already
  sport-tagged, so splitting later is mechanical.

**Cross-sport comparisons survive either layout** — the "nice commonalities" are a
*generation-time* property (the model reasoning over per-sport slices), not a property of the
index being unified. Storage layout is orthogonal to the comparison feature.

**Rebuild authority:** keep **Rebuild a single global, unscoped operation** (an all-rulesets
admin act). Do NOT try to scope rebuild without per-sport indices — a global rebuild necessarily
re-embeds rulesets a scoped operator can't see, and reads golds/sources spanning them. Give a
scoped Director `sources.curate` for their rulesets but not `index.rebuild`. Add two build-time
rules: intersect an authored gold's sports with the **author's** allowed rulesets (a scoped
author can't fan content into rulesets they lack); keep curation filtered to the caller's
rulesets.

## Token economics (multiple indices)

Multiple indices are **token-neutral-to-favorable**; index count is not the cost driver.
- **Build embeddings:** total is the same (each chunk embedded once). Per-ruleset indices *lower*
  rebuild cost — re-embed only the changed ruleset, vs. one index re-embedding everything.
- **Query embeddings:** one question embedding per query, reused across all stores. No change.
- **Generation (the expensive meter):** input = prompt + retrieved passages + question. Cost
  tracks **(# rulesets retrieved) × k**, independent of physical index count. A "compare A vs B"
  query pulls k from each = 2k passages whether they live in one store or two.

So the real cost driver is **retrieval breadth**, not layout. Adding badminton + curling only
costs more when a user retrieves across all four. Engineer against it with (a) defaulting to the
user's *selected*/*allowed* rulesets, and (b) the **global top-k budget** (Area 2) so context
stays flat as rulesets grow.

## Generalizing beyond sports

The only per-sport assumptions are `DEFAULT_SPORTS` and one prompt line. Going domain-agnostic is:
rename the concept **"sport" → "ruleset"/"domain"** (mechanical refactor), de-hardcode the list
and the prompt, and make the **registry (1b)** first-class (it becomes the home for "here are the
rulesets, their names, and where to download each"). This also makes **per-user access (Area 3)**
more compelling — "which rulesets can this user see" is a natural feature across mixed domains
(sports + a company's own policy docs) in a way it isn't within disc sports alone.

## Ranking & sequence

- **Effort (low→high):** Area 2 (days) < Area 1a (small) < Area 1b registry (medium) < Area 3
  (weeks; subtle leak points).
- **Dependencies:** Area 2 is a prerequisite for Area 3's precision (exact per-question rulesets);
  Area 1a helps Area 3 (one authoritative ruleset list). Area 3's index decision (A vs B) is
  independent but settle it before building enforcement.
- **Suggested order:** (0) kill `DEFAULT_SPORTS` (1a) → (1) multi-select `sports[]` + `qa_log`
  widening + global top-k (Area 2) → (2) per-user allowlist, Option A, rebuild global (Area 3) →
  (later) ruleset registry + `sources.add` (1b) + generalization; per-ruleset indices (B) only if
  isolation is ever required.
- **Add badminton + curling:** content/ops task — depends on the registry/point-and-download and
  the 1a fix (or the golds silently drop). Copyrighted docs (BWF, WCF) handled by point-and-download.

**No hard-breaking changes** if singular `sport` stays a compat alias (Area 2) and the ruleset
allowlist defaults to `*` (Area 3). Additive schema bumps: `qa_log` (`sports` list) and optionally
`gold` (derived `sports`), both backward-compatible via read-time derivation for legacy rows.
