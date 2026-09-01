# RBAC — capabilities and the eight rungs

_Last updated: 2026-08-31_

Authorization is **capability-based**: every endpoint gates on a named capability
(`require_capability(cap)`), and a role is a bundle of capabilities. `/me` returns
the caller's `role` (a level id, `level0`…`level8`), numeric `level`, the
capability bundle, and `allowed_domains`. `ROLE_CAPABILITIES` is keyed by level;
`ROLE_LEVELS` carries each level's name/color/description for the badge. See
[`roles.md`](roles.md) for the overview and [`users-tab.md`](users-tab.md) for the
admin UI.

> **A second axis — domain scoping.** On top of capabilities, each user has an
> `allowed_domains` set: role = *what* you can do, `allowed_domains` = *which
> domains* you can do it in. Admin/Superuser (level ≥ 7) are unscoped; scoped
> Reviewers/Directors see and act only within their domains. Stored/managed
> separately (see `src/rulebook/allowed_domains.py`, the Users tab, and
> `_admin_domain_scope`/`_in_scope` in `api/main.py`).

## 1. Vocabulary — source, chunk, passage

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

## 2. The capability set

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
tab-by-tab as they climb. `advanced.view` and the `*.view.all` / curate / users caps are
the operator extras layered on top.

| Capability | Guards |
|---|---|
| `activity.view` | open the **Your activity** page shell + the nav button (personal, self-scoped) |
| `advanced.view` | + the retrieval machinery: passages and the Sources tab |
| `feedback.view` | Feedback tab — **your own** rows |
| `feedback.view.all` | Feedback tab shows **everyone's** rows |
| `golds.view` | Golds tab — **your own** rows |
| `golds.view.all` | Golds tab shows **everyone's** rows |
| `questions.view.all` | Questions tab shows **everyone's** rows, stamped with the asker |
| `golds.edit.own` | Edit a gold you authored |
| `golds.clone` | Clone another's gold into your own, then edit as your own |
| `golds.curate` | toggle a gold's *Incl.* |
| `sources.view` | Sources tab (the corpus of documents) |
| `sources.curate` | toggle a source's inclusion |
| `sources.add` | upload a new source — **future** |
| `index.rebuild` | the *Rebuild index* button |
| `attribution.view` | the **Audit** tab (who changed shared state). Row authors on feedback/gold/question lists ride with the `*.view.all` tier (L5), not this |
| `users.view` | Users tab — see rows |
| `users.change_role` | change a user's role |
| `users.add` | add an invitee |
| `users.remove` | hard-delete an invite |
| `users.rename` | rename a user's label |
| `roles.manage` | edit the RBAC config itself (future — see the permission-model roadmap) |

Note there is no `golds.edit.any`: nobody edits another person's gold **in place** —
you **clone** it (§4). You **may** edit **your own** feedback (re-rate, edit the comment)
from *Your activity* — a re-POST to `/feedback`, last-write-wins per `qa_id`, gated by the
same per-field caps (`rate`, `feedback.comment`); nobody edits another person's feedback.

## 3. The eight rungs (levels)

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
| **5** | read all (with authors), write own | `feedback.view.all`, `golds.view.all`, `questions.view.all` |
| **6** | operator | `golds.curate`, `golds.clone`, `sources.curate`, `index.rebuild`, `attribution.view` |
| **7** | admin | `users.view`, `users.change_role`, `users.add` |
| **8** | superuser | `users.remove`, `users.rename`, `roles.manage` |

Machine names are `level0` … `level8`; there are no aliases.

Reference matrix (✓ = has it; columns are cumulative left→right, by level):

| Capability | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| `ask`, `rate`, `feedback.tag` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `activity.view` · `feedback.view` (own) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `feedback.comment` | | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `gold.author` · `golds.view` · `golds.edit.own` (own) | | | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `advanced.view` · `passages.view` · `sources.view` | | | | ✓ | ✓ | ✓ | ✓ | ✓ |
| `feedback.view.all` · `golds.view.all` · `questions.view.all` | | | | | ✓ | ✓ | ✓ | ✓ |
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
- **4→5** is scope: self → all (read), **with authorship**. Level 4 sees only its own
  feedback/golds/questions; level 5 sees everyone's, each stamped with who wrote/asked it.
  (We deliberately *don't* do blind review — in a small community, hiding authorship from a
  reviewer is more confusing than useful.) Tab counts read "your X" at 4, the global total at 5.
- **5→6** is **write on others' assets** (curate, clone, rebuild) plus the **Audit** tab —
  the log of who changed shared state (`attribution.view`). Row authorship is already visible
  at 5; what 6 adds is the *mutation* powers and the audit trail. The boundary to be most
  deliberate about.
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

## 4. Cross-cutting behaviors

Four things aren't single-endpoint gates; they're patterns the rungs above lean on.

**Self vs. all (the `.all` capabilities).** The Advanced list endpoints
(`/advanced/{golds,feedback,sources}`) take an **owner filter**. Without `*.view.all`, they
return only rows authored by the caller and the tab count reflects that subset ("your
X"). With `*.view.all`, they return everyone's and count the global total. One filter,
two capabilities — no separate "own" vs "all" endpoints.

**Clone, not edit-any (golds are owned entities).** No rung edits another person's
gold in place. Own golds show **Edit** (`golds.edit.own`); at #6+ others' golds show
**Clone** (`golds.clone`) — the clone is a new gold owned by the cloner, which they then
Edit as their own. Provenance is never mutated. A gold is an **owned entity**: it carries
a `gold_id` (`v3` schema; legacy rows resolve to `gold_id == qa_id`), plus its author and
the `qa_id` it answers. `POST /gold` upserts the caller's *own* gold for a qa_id (reusing
their id, minting one otherwise) — it can never touch another author's gold, which *is*
the `edit.own` enforcement. `POST /advanced/golds/{gold_id}/clone` (gated `golds.clone`)
forks a gold into a new one owned by the caller. Several candidate golds can coexist for
one question; curation (`Incl.`) picks which feed the index, which is keyed by `gold_id`.

**The attribution wall (#5 → #6).** Below the wall, #5 can read *everyone's* gold and
feedback **content** but the rows are **anonymous** — no author shown (`attribution.view`
is absent). At #6+ each row shows **who wrote it**. Knowing which player gave which
rating or wrote which answer is a privacy step-up, reserved for trusted operators.

**Audit is action-scoped, not rung-scoped.** Every **content write** already carries
`author` + `timestamp` in the append-only jsonl (`qa_log`, `feedback`, `gold`), so #1–#5
activity is on the record as a byproduct. The genuine gap is **shared-state mutations**
(`golds.curate`, `golds.clone`, `sources.curate`, `index.rebuild`, `users.*`). The rule:
*every state-changing endpoint appends one audit row* (actor, action, target, timestamp,
before→after) to a dedicated `audit.jsonl`. `log_audit(actor, action, target, detail)`
writes it after each shared-state write commits; `GET /advanced/audit` returns the trail
newest-first, gated on `attribution.view` (level 6+) — seeing who did what is the same
trust tier as the attribution wall.

## 5. Enforcement — one source of truth

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
  resource checks (§4) live at the endpoint, not just the button.

## 6. Non-goals (for now)

- Per-field ACLs beyond the self/all and own/clone splits.
- Editable feedback (feedback is read-only data at every rung).
- Group/team scoping (the Linux self→group→all middle tier); we go self → all only.
- Defining/re-bundling permissions from the UI (data-driven, editable roles). A capability
  only *acts* because code checks it at an enforcement point, so inventing new enforcement
  stays a code change regardless. This is future work — tracked in the permission-model
  roadmap (issues #200–#203).
