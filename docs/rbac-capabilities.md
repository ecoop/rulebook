# RBAC — capabilities and the eight rungs

_Last updated: 2026-08-12_

> **Status: bundles match the eight rungs (belt-named); behaviours follow.** The
> capability *mechanism* **and** the eight-rung *bundles* now ship in `roles.py` +
> `api/main.py`: every endpoint gates on a capability, `/me` returns the caller's
> bundle, and `ROLE_CAPABILITIES` encodes rungs #1–#8 as **judo belts** (white→red,
> §4). Legacy machine names (`novice`/`evaluator`/`admin`/`superuser`) alias to their
> belt via `ROLE_ALIASES`, so the live seed and `roles.jsonl` keep resolving with **no
> data migration** — `resolve_role` normalizes them, and the frontend's role checks
> read belts. The four interior belts (yellow/green/blue/brown) exist as bundles but
> aren't in the picker yet. What's still ahead is **behaviour**, not vocabulary:
> self→all filtering, the clone flow (golds as owned entities), the attribution wall,
> the audit log, and the rest of the frontend — sequenced in §9. Extends
> [`roles.md`](roles.md) (the original ladder; still used for role ordering).

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

A capability is a stable string guarding exactly one action. Names outlive UI labels: the
Advanced page is guarded by `advanced.view` even while the HTTP route is still `/admin/*`
and the page still reads "Admin" until the relabel — naming it `admin.*` would fossilize.
Routes stay `/admin/*` (an internal management-API namespace, never shown on the page).

**Main page**

| Capability | Guards |
|---|---|
| `ask` | POST `/ask` |
| `rate` | a numeric 1–5 rating on an answer |
| `feedback.tag` | attach issue tags to a rating |
| `feedback.comment` | attach a free-text comment (≤ 400 chars) |
| `gold.author` | suggest a gold answer for your own Q&A |
| `passages.view` | see the Retrieved passages panel under an answer |

**Advanced surface**

| Capability | Guards |
|---|---|
| `advanced.view` | see the Advanced page shell + the nav button |
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

## 4. The eight rungs

The rungs are named for **Kodokan judo belts** (white → red). White-through-black darkens
as a steady progression; **red (superuser) breaks the ramp on purpose** — an honorary
grade that signals "not simply the next rung up," which is exactly how superuser sits
apart from the ladder. Every higher rung includes everything below it; the table lists
only **what each rung adds**.

| # | Belt | Description | Adds |
|---|---|---|---|
| **1** | ⬜ white | casual player | `ask`, `rate`, `feedback.tag` |
| **2** | 🟨 yellow | + explain a rating | `feedback.comment` |
| **3** | 🟧 orange | + suggest answers | `gold.author` |
| **4** | 🟩 green | peek behind the curtain — self, read-mostly | `advanced.view`, `passages.view`, `feedback.view`, `golds.view`, `golds.edit.own`, `sources.view` |
| **5** | 🟦 blue | read all, write own | `feedback.view.all`, `golds.view.all` |
| **6** | 🟫 brown | operator | `golds.curate`, `golds.clone`, `sources.curate`, `index.rebuild`, `attribution.view` *(+ audit — §5)* |
| **7** | ⬛ black | admin | `users.view`, `users.change_role`, `users.add` |
| **8** | 🟥 red | superuser | `users.remove`, `users.rename`, `roles.manage` |

`suspended` is the **non-belt floor** — blocked from play, below white. The four legacy
machine names map to belts and stay valid via aliases (see below): `novice`→white,
`evaluator`→orange, `admin`→black, `superuser`→red.

Reference matrix (✓ = has it; columns are cumulative left→right):

| Capability | 1 w | 2 y | 3 o | 4 g | 5 bl | 6 br | 7 bk | 8 r |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| `ask`, `rate`, `feedback.tag` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `feedback.comment` | | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `gold.author` | | | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `advanced.view` · `passages.view` | | | | ✓ | ✓ | ✓ | ✓ | ✓ |
| `feedback.view` · `golds.view` (own) | | | | ✓ | ✓ | ✓ | ✓ | ✓ |
| `golds.edit.own` · `sources.view` | | | | ✓ | ✓ | ✓ | ✓ | ✓ |
| `feedback.view.all` · `golds.view.all` | | | | | ✓ | ✓ | ✓ | ✓ |
| `golds.curate` · `golds.clone` | | | | | | ✓ | ✓ | ✓ |
| `sources.curate` · `index.rebuild` | | | | | | ✓ | ✓ | ✓ |
| `attribution.view` | | | | | | ✓ | ✓ | ✓ |
| `users.view` · `users.change_role` · `users.add` | | | | | | | ✓ | ✓ |
| `users.remove` · `users.rename` · `roles.manage` | | | | | | | | ✓ |

What each boundary means, in one line:
- **orange→green (#3→#4)** is the Advanced button appearing — the first "behind the
  curtain" rung.
- **green→blue (#4→#5)** is scope: self → all (read). Green sees only its own
  feedback/golds; blue sees everyone's. Tab counts read "your X" at green, the global
  total at blue.
- **blue→brown (#5→#6)** is two things at once: **write on others' assets** (curate,
  clone, rebuild) *and* the **attribution wall** (§5). The boundary to be most deliberate
  about.
- **brown→black (#6→#7)** is people: the Users tab, role changes, and inviting users.
- **black→red (#7→#8)** is the **destructive** roster ops (remove, rename) plus editing
  the RBAC config itself. Black adds *and* adjusts users; red is the only rung that can
  *delete or rename* one — matching red's honorary, apart-from-the-ladder status.

### Belt palette (for role badges)

Role names are near-invisible — a player never sees their belt; only #6+ (brown+) see
roles at all, in the Users tab. So the belt shows up as a small colored badge there (and
at a future "level up" moment). Colors chosen for contrast; red/brown/green collide under
common colorblindness, so a badge always pairs the color with the belt name.

| Belt | Hex | | Belt | Hex |
|---|---|---|---|---|
| white | `#E8E8E8` | | blue | `#2C64B4` |
| yellow | `#E5B80B` | | brown | `#7A4A2B` |
| orange | `#E07A20` | | black | `#1A1A1A` |
| green | `#3A8C3A` | | red | `#C4272E` |

**Level up (future).** The one place a belt might be *earned* rather than assigned: a
promotion mechanic that bumps a player a rung on sustained activity (e.g. asked 10
questions *and* rated 10 answers → white → yellow). Noted so the model leaves room for
it; assignment today is manual (seed ⊕ `roles.jsonl`).

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
   `has_capability`, `/me` carries `capabilities`. (First-cut roles; realign to §4.)
2. **Realign bundles to the eight rungs** — the tag/comment split, `passages.view`,
   `.all` capabilities, clone/attribution capabilities in `ROLE_CAPABILITIES`; name the
   four new rungs.
3. **Self→all filtering** — owner filter + per-user counts on the Advanced list endpoints.
4. **Golds as owned entities + clone** — the schema change (§5) and the `POST /gold`
   ownership check; Edit vs Clone in the Golds tab.
5. **Audit log** — `audit.jsonl` + a write on every shared-state mutation.
6. **Frontend gating** — tabs/columns/buttons by capability; retire `ROLE_RANK` /
   `ROLE_LADDER_FALLBACK`; the atomic **Admin→Advanced** relabel; the passages-panel
   redesign; the new rungs in the picker.
7. *(later)* **data-driven bundles**, then **the permissions editor** (§8).

## 10. Non-goals (for now)

- Per-field ACLs beyond the self/all and own/clone splits.
- Editable feedback (feedback is read-only data at every rung).
- Group/team scoping (the Linux self→group→all middle tier); we go self → all only.
- Inventing new enforcement points from the UI (§8).
