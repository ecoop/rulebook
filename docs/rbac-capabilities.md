# RBAC — capabilities and the eight rungs

_Last updated: 2026-08-15_

> **Status: bundles match the eight rungs (numbered levels); behaviours follow.** The
> capability *mechanism* **and** the eight-rung *bundles* ship in `roles.py` +
> `api/main.py`: every endpoint gates on a capability, `/me` returns the caller's
> `role` (a level id, `level0`…`level8`), numeric `level`, and capability bundle.
> `ROLE_CAPABILITIES` is keyed by level; `ROLE_LEVELS` carries each level's color +
> description for the badge. **The old names (`superuser`, `novice`, …) are gone** — no
> aliases; the seed and any `roles.jsonl` are migrated to level ids (a one-time step at
> deploy — see below). What's still ahead is **behaviour**, not vocabulary: self→all
> filtering, the clone flow (golds as owned entities), the attribution wall, the audit
> log, the level badge, and the rest of the frontend — sequenced in §9. Extends
> [`roles.md`](roles.md) (the original ladder; still used for role ordering).
>
> **Deploy migration (one-time).** Since aliases are gone, the seed secret must use
> level ids before this deploys, or `superuser` resolves to nothing and Coop loses
> access. Map `novice`→`level1`, `evaluator`→`level3`, `admin`→`level7`,
> `superuser`→`level8` in `RULEBOOK_INITIAL_ROLES` (and any `roles.jsonl` rows).

## 1. The ladder wasn't wrong — it was too coarse

The original five-tier ladder (`suspended < novice < evaluator < admin < superuser`)
gated by **rank**: `require_role("admin")` meant `rank(you) >= rank(admin)`. That reads
access off a single number, which can't express per-feature asks like "see the Advanced
page but not the Users tab" or "edit your own gold but not others'."

Working the real requirements through, though, a surprising thing fell out: the desired
roles form a **monotonic chain** — each is the previous plus more:

> #1 ⊂ #2 ⊂ #3 ⊂ #4 ⊂ #5 ⊂ #6 ⊂ #7 ⊂ #8

So this *is* a ladder — just a finer, eight-rung one instead of a blunt five-rung one.
Monotonic is a feature: it's easy to reason about, and "higher rung ⇒ strictly more."

**Capabilities remain the mechanism even for a monotonic model**, for three reasons:
they express a nesting ladder trivially (each bundle ⊇ the last); they let orthogonal
axes like **self vs. all** and **attribution** ride alongside the rungs without
inventing a rank for every combination; and they keep the escape hatch open for the one
non-monotonic move we considered and rejected (a Users-only admin) without a rewrite.
So: the rungs are the policy, capabilities are the mechanism.

## 2. Vocabulary — source, chunk, passage

Three words, each meaning exactly one thing, used consistently everywhere (UI labels,
capability names, code):

| Term | Meaning | Where it shows |
|---|---|---|
| **source** | an ingested document (e.g. "Goaltimate Official Rules") | the Advanced **Sources** tab manages these |
| **chunk** | the build-time unit a source is split into during ingestion | backstage — never shown to end users |
| **passage** | a *retrieved chunk*: an excerpt pulled from a source to answer a query | the main-page **Retrieved passages** panel |

This is standard RAG parlance (cf. Dense Passage Retrieval), not local coinage. It
retires an earlier ambiguity: "sources" now means the documents *only*, so the Advanced
tab keeps the name **Sources** (`sources.*`) and the answer-evidence panel is **Retrieved
passages** (`passages.view`) — no collision, no rename.

## 3. The capability set

A capability is a stable string guarding exactly one action. Names outlive UI labels:
`advanced.view` was named for what it guards from the start, so the Admin→Advanced relabel
(page title, component, `#/advanced` hash, `/advanced/*` routes) was a pure rename with no
capability churn — the fossil an `admin.*` name would have left never happened.

**Main page**

| Capability | Guards |
|---|---|
| `ask` | POST `/ask` |
| `rate` | a numeric 1–5 rating on an answer |
| `feedback.tag` | attach issue tags to a rating |
| `feedback.comment` | attach a free-text comment (≤ 400 chars) |
| `gold.author` | suggest a gold answer for your own Q&A |
| `passages.view` | see the Retrieved passages panel under an answer |

**Your-activity / Advanced surface**

Both live on the same page (`AdvancedApp`). The self-scoped "revisit your own work"
caps sit LOW on the ladder — everyone gets a personal **Your activity** page that grows
tab-by-tab as they climb (see #74/#51). `advanced.view` and the `*.view.all` /
curate / users caps are the operator extras layered on top.

| Capability | Guards |
|---|---|
| `activity.view` | open the **Your activity** page shell + the nav button (personal, self-scoped) |
| `advanced.view` | + the retrieval machinery: passages and the Sources tab |
| `feedback.view` | Feedback tab — **your own** rows |
| `feedback.view.all` | Feedback tab shows **everyone's** rows |
| `golds.view` | Golds tab — **your own** rows |
| `golds.view.all` | Golds tab shows **everyone's** rows |
| `golds.edit.own` | Edit a gold you authored |
| `golds.clone` | Clone another's gold into your own, then edit as your own |
| `golds.curate` | toggle a gold's *Incl.* |
| `sources.view` | Sources tab (the corpus of documents) |
| `sources.curate` | toggle a source's inclusion |
| `sources.add` | upload a new source — **future** (see [`sources-upload.md`](sources-upload.md)) |
| `index.rebuild` | the *Rebuild index* button |
| `attribution.view` | see the author identity on feedback / gold rows |
| `users.view` | Users tab — see rows |
| `users.change_role` | change a user's role |
| `users.add` | add an invitee |
| `users.remove` | hard-delete an invite |
| `users.rename` | rename a user's label |
| `roles.manage` | edit the RBAC config itself (the future data-driven editor, §8) |

Note there is no `golds.edit.any`: nobody edits another person's gold **in place** —
you **clone** it (§5). Feedback is **never editable** at any rung; it's read-only data.

## 4. The eight rungs (levels)

Roles are **numbered levels 0–8**. The number makes the ordering self-evident (level 5
outranks level 4, no lore required) — the concern any color/word scheme can't answer on
its own. **Level 0 is a suspended account** (no access); 1–8 are the rungs. Each level
also carries a **color** (a judo-belt palette, for a fun badge) and a one-line
description — see the palette below. Every higher level includes everything below it; the
table lists only **what each level adds**.

| Level | Description | Adds |
|---|---|---|
| **0** | suspended — no access | *(none)* |
| **1** | beginner — ask, rate, and revisit your own | `ask`, `rate`, `feedback.tag`, `activity.view`, `feedback.view` |
| **2** | + explain a rating | `feedback.comment` |
| **3** | + suggest & revisit your own golds | `gold.author`, `golds.view`, `golds.edit.own` |
| **4** | + the retrieval machinery — self, read-mostly | `advanced.view`, `passages.view`, `sources.view` |
| **5** | read all, write own | `feedback.view.all`, `golds.view.all` |
| **6** | operator | `golds.curate`, `golds.clone`, `sources.curate`, `index.rebuild`, `attribution.view` *(+ audit — §5)* |
| **7** | admin | `users.view`, `users.change_role`, `users.add` |
| **8** | superuser | `users.remove`, `users.rename`, `roles.manage` |

Machine names are `level0` … `level8`; there are no aliases (the earlier
novice/evaluator/… names were migrated — see the status note).

Reference matrix (✓ = has it; columns are cumulative left→right, by level):

| Capability | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| `ask`, `rate`, `feedback.tag` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `activity.view` · `feedback.view` (own) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `feedback.comment` | | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `gold.author` · `golds.view` · `golds.edit.own` (own) | | | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `advanced.view` · `passages.view` · `sources.view` | | | | ✓ | ✓ | ✓ | ✓ | ✓ |
| `feedback.view.all` · `golds.view.all` | | | | | ✓ | ✓ | ✓ | ✓ |
| `golds.curate` · `golds.clone` | | | | | | ✓ | ✓ | ✓ |
| `sources.curate` · `index.rebuild` | | | | | | ✓ | ✓ | ✓ |
| `attribution.view` | | | | | | ✓ | ✓ | ✓ |
| `users.view` · `users.change_role` · `users.add` | | | | | | | ✓ | ✓ |
| `users.remove` · `users.rename` · `roles.manage` | | | | | | | | ✓ |

What each boundary means, in one line:
- **1–3** is *your own work*: everyone gets the **Your activity** page (`activity.view`)
  and can revisit their own ratings (`feedback.view`); level 3 adds authoring and
  revisiting their own golds. The page is never empty — it grows tab-by-tab as you climb.
- **3→4** is the *retrieval machinery* appearing — passages and the Sources tab. Still
  self-scoped (you see only your own feedback/gold rows), just "behind the curtain."
- **4→5** is scope: self → all (read). Level 4 sees only its own feedback/golds; level 5
  sees everyone's. Tab counts read "your X" at 4, the global total at 5.
- **5→6** is two things at once: **write on others' assets** (curate, clone, rebuild) *and*
  the **attribution wall** (§5). The boundary to be most deliberate about.
- **6→7** is people: the Users tab, role changes, and inviting users.
- **7→8** is the **destructive** roster ops (remove, rename) plus editing the RBAC config
  itself. Level 7 adds *and* adjusts users; level 8 is the only one that can *delete or
  rename* one.

### Level palette (for the badge)

Role names are near-invisible — a player never sees their level; only #6+ see roles at
all (in the Users tab). So the level shows as a small **colored badge** — the color is
judo-belt flavor, and the rung number is prefixed so the order is unambiguous
(`4 · green`). Red/brown/green collide under common colorblindness, so the badge always
pairs color with the number + label. Colors + descriptions live in `ROLE_LEVELS`
(`roles.py`) as the single source; `/me` returns the caller's `level`.

| Level | Color | Description | | Level | Color | Description |
|---|---|---|---|---|---|---|
| 0 | `#9AA0A6` | suspended — no access | | 5 | `#2C64B4` | reviews everyone's items |
| 1 | `#E8E8E8` | beginner — ask and rate | | 6 | `#7A4A2B` | operator — curates, rebuilds |
| 2 | `#E5B80B` | can comment on answers | | 7 | `#1A1A1A` | admin — manages users |
| 3 | `#E07A20` | can suggest gold answers | | 8 | `#C4272E` | superuser — full control |
| 4 | `#3A8C3A` | sees the workings (own) | | | | |

**Level up (future).** The one place a level might be *earned* rather than assigned: a
promotion mechanic that bumps a player a level on sustained activity (e.g. asked 10
questions *and* rated 10 answers → level 1 → level 2). The number makes "leveling up"
read naturally. Noted so the model leaves room for it; assignment today is manual
(seed ⊕ `roles.jsonl`).

## 5. Cross-cutting behaviors

Four things aren't single-endpoint gates; they're patterns the rungs above lean on.

**Self vs. all (the `.all` capabilities).** The Advanced list endpoints
(`/admin/{golds,feedback,sources}`) take an **owner filter**. Without `*.view.all`, they
return only rows authored by the caller and the tab count reflects that subset ("your
X"). With `*.view.all`, they return everyone's and count the global total. One filter,
two capabilities — no separate "own" vs "all" endpoints.

**Clone, not edit-any (golds become owned entities).** No rung edits another person's
gold in place. Own golds show **Edit** (`golds.edit.own`); at #6+ others' golds show
**Clone** (`golds.clone`) — the clone is a new gold owned by the cloner, which they then
Edit as their own. Provenance is never mutated. This requires a **schema change**: today
a gold is keyed by question (one active gold per `qa_id`, latest wins); to support clones
a gold must be an **owned entity** (its own id + author + the `qa_id` it answers). A nice
side effect — several candidate golds can coexist for one question and curation (`Incl.`)
picks which feed the index.

> **Landed (backend).** Golds now carry a `gold_id` (`v3` schema); legacy rows resolve
> to `gold_id == qa_id`, so nothing needs migrating. `POST /gold` upserts the caller's
> *own* gold for a qa_id (reuses their id, mints one otherwise) — it can never touch
> another author's gold, which *is* the `edit.own` enforcement.
> `POST /admin/golds/{gold_id}/clone` (gated `golds.clone`) forks a gold into a new one
> owned by the caller. Curation and the index builder are keyed by `gold_id`. The
> Golds-tab **Edit vs Clone** buttons (driven by the new `is_own` flag on each row) land
> with the frontend-gating slice.

**The attribution wall (#5 → #6).** Below the wall, #5 can read *everyone's* gold and
feedback **content** but the rows are **anonymous** — no author shown (`attribution.view`
is absent). At #6+ each row shows **who wrote it**. Knowing which player gave which
rating or wrote which answer is a privacy step-up, reserved for trusted operators.

**Audit is action-scoped, not rung-scoped.** Every **content write already** carries
`author` + `timestamp` in the append-only jsonl (`qa_log`, `feedback`, `gold`), so #1–#5
activity is on the record as a byproduct. The genuine gap is **shared-state mutations**
(`golds.curate`, `golds.clone`, `sources.curate`, `index.rebuild`, `users.*`), which
vanish today. The rule: *every state-changing endpoint appends one audit row* (actor,
action, target, timestamp, before→after) to a dedicated `audit.jsonl`. Level-independent,
cheap (append-only), and it dissolves "where does audit start?" — it starts at the first
action that touches something other than your own, which is exactly rung #6.

> **Landed.** `log_audit(actor, action, target, detail)` writes to `audit.jsonl`; every
> shared-state endpoint calls it after the write commits (`golds.curate`, `golds.clone`,
> `sources.curate`, `index.rebuild`, `users.change_role`/`add`/`remove`/`rename`).
> `GET /admin/audit` returns the trail newest-first, gated on `attribution.view` (level
> 6+) — seeing who did what is the same trust tier as the attribution wall. An Audit
> *tab* is a frontend follow-up; the record exists now.

## 6. Enforcement — one source of truth

- **Backend.** `require_capability(cap)` gates every endpoint; `ROLE_CAPABILITIES:
  dict[str, frozenset[str]]` + `has_capability(role, cap)` live in `roles.py`. Unknown
  roles resolve to an empty bundle — fail closed. When `demo_mode` is off the deploy is
  anonymous and only the public tier (`ask`, `rate`) is allowed.
- **`/me` returns the caller's `capabilities`** (sorted). This is the contract the UI
  renders against — the frontend never hardcodes "role X sees tab Y"; it asks "do I have
  `golds.curate`?" and shows the control or not.
- **The rule that keeps them honest:** the UI *hides* what you can't do; the backend
  *enforces* it. Hiding a button is UX, not security — the endpoint still checks the
  capability, so a hand-crafted request is rejected the same way. The `.own`/clone
  resource checks (§5) live at the endpoint, not just the button.

## 7. UI and build notes (frontend / pipeline slices)

Design decisions captured here so they aren't lost; they land in the frontend and
build-side slices, not the RBAC backend.

- **Retrieved passages panel.** One row per passage; a **scannable metadata line**
  (`sport · document · § section · page`, with the match `d` right-aligned) and the
  passage text **collapsed** behind a disclosure. Header carries a one-line gloss:
  *"d = distance from your question — lower is a closer match."* Golds retrieved as
  passages get a `gold` badge and (per `golds.view` scope) a reference/link to the gold.
  Caption: *"The N excerpts the model used to write the answer above."*
- **The document must be shown.** Each passage already carries a `source`; surface it, so
  a citation reads `goaltimate · Goaltimate Official Rules · § XIII.D.4 · p.21` and a
  supplement is never an orphaned "p.21 of what?". Map raw filenames to a friendly
  **title** once (a per-source display name).
- **Advanced button.** Rename "Admin" → **"Advanced"**; move it into the header **top-
  right as a bordered button** (currently it's a bland link buried under the expanded
  passages panel).
- **Whitespace at the source.** PDF-extracted passages render as one-word-per-line garbage
  because the extraction emitted stray newlines. Normalize on display *and* clean at
  **extraction / chunk-build** time so the index itself is clean.

## 8. Later (NOT near-term): define & edit permissions from the UI

The end-state is managing the RBAC config as **data** — create a role, re-bundle
capabilities — live, no deploy. So phase-1 code shouldn't paint us out of it:

- **Role bundles become data.** Move `ROLE_CAPABILITIES` into a GCS object (same
  read-with-TTL pattern as roles/invites); a `roles.manage` superuser edits bundles in a
  new surface. Assignment (`token → role`) is unchanged.
- **A capability registry** (string + description + which surface it guards) so the editor
  renders labeled checkboxes, not raw strings.
- **The hard limit, stated plainly.** You can data-drive *which capabilities a role
  bundles*, but a capability only *does* something because **code checks it** at an
  enforcement point. So the UI can **create roles and re-bundle existing capabilities**;
  **inventing new enforcement** stays a code change. The editor should make that boundary
  obvious (existing capabilities pickable; new ones "declared but unguarded" until wired).
- **Guardrails.** Can't delete a capability an endpoint references; a token pointing at a
  deleted role falls back to `DEFAULT_ROLE`; a superuser can't strip their own
  `roles.manage` and lock everyone out.

## 9. Sequencing

The mechanism has landed; the rest is slices. The frontend ones edit
`web/src/AdminApp.tsx`, so they follow the sorting + rename work already on `main`.

1. ✅ **Capability mechanism** — `require_capability`, `ROLE_CAPABILITIES`,
   `has_capability`, `/me` carries `capabilities` + numbered levels + the badge.
2. ✅ **Realign bundles to the eight rungs** — tag/comment split, `passages.view`,
   `.all` capabilities, clone/attribution capabilities; numbered-level names.
3. ✅ **Self→all filtering** — `GET /admin/golds` and `/admin/feedback` return only the
   caller's own rows without `*.view.all` (matched on the `author` label). Behaviour-
   preserving today (only level7/8 reach those tabs, and they hold `.all`); the "your X"
   count labels land with the frontend-gating slice.
4. ✅ **Golds as owned entities + clone** — `gold_id` (`v3`), `POST /gold` upserts the
   caller's own gold, `POST /admin/golds/{gold_id}/clone`, curation + index keyed by
   `gold_id`. The Golds-tab Edit-vs-Clone buttons (via `is_own`) ride with the frontend
   slice.
5. ✅ **Audit log** — `audit.jsonl` + a write on every shared-state mutation;
   `GET /admin/audit` (attribution.view). The Audit tab rides with the frontend slice.
6. ✅ **Frontend capability-gating** — `AdminApp` renders tabs/controls off
   `/me`'s `capabilities` (page at `advanced.view`, each tab by its cap, Rebuild /
   Incl. / source-toggle / role-picker / add / remove / rename each behind its cap),
   Golds shows **Edit** (own) vs **Clone** (others'), the **Audit tab** lands, and
   `App` gates the nav link + gold authoring on capabilities — `ROLE_RANK` retired.
   The surface now opens to levels 4–6.
7. ✅ **Admin→Advanced relabel** — page title + a top-right "Advanced" button,
   `AdminApp`→`AdvancedApp`, `#/admin`→`#/advanced` (old hash redirected),
   `/admin/*`→`/advanced/*` routes with their fetch calls + tests. Internal `Admin*`
   model/type names are left as a soft namespace (no behaviour, no user text).
   *(Still open, separate: the retrieved-passages panel redesign — a main-page item.)*
8. *(later)* **data-driven bundles**, then **the permissions editor** (§8).

## 10. Non-goals (for now)

- Per-field ACLs beyond the self/all and own/clone splits.
- Editable feedback (feedback is read-only data at every rung).
- Group/team scoping (the Linux self→group→all middle tier); we go self → all only.
- Inventing new enforcement points from the UI (§8).
