# RBAC, phase 2 — capabilities instead of a ladder

_Last updated: 2026-08-12_

> **Status: backend landed; frontend pending.** The capability layer (§2–§5) now
> ships in `roles.py` + `api/main.py`: every endpoint gates on a capability via
> `require_capability`, `/me` returns the caller's capability bundle, and the three
> new roles are defined and tested. The existing five behave **exactly** as before
> (mechanism swap, not policy change) — so nothing is visibly different yet. What's
> left: the **frontend** renders tabs/columns/buttons off `/me`'s capabilities, adds
> the new roles to the picker, and carries the atomic Admin→Advanced relabel (see
> **Sequencing**). This extends [`roles.md`](roles.md) (the monotonic ladder, still
> used for role *ordering*). §7 (define/edit permissions from the UI) stays **not
> near-term**.

## 1. Why the ladder can't do what we now want

Today a role is a **rank**: `suspended < novice < evaluator < admin < superuser`, and
every gate is one comparison — `require_role("admin")` means `rank(you) >= rank(admin)`.
That makes access **monotonic**: anything an admin-rank endpoint allows, *every*
admin automatically gets. There is no way to say "admin page, but not the Users tab,"
because Users-tab access *is* admin-rank — granting the page grants the tab.

The new asks break monotonicity:

- see the admin page **but not** the Users tab
- view the Golds tab **but not** toggle *Incl.* or edit answers
- edit **your own** gold answers but **not** other people's

None of these are expressible as "further up / further down one line." They're
**per-feature**, so roles have to become **bundles of named capabilities** rather than
points on a ladder. (This is the "pet → cattle" shift: a role is *defined by what it can
do*, not hand-placed in a hierarchy.)

## 2. The capability set (small, closed, code-defined)

A capability is a stable string that guards exactly one thing. Keep the set small and
coarse — one per meaningful action, not per field.

**Main app**

| Capability | Guards |
|---|---|
| `ask` | POST `/ask` |
| `rate` | POST `/feedback` (star rating) |
| `feedback.annotate` | tags + notes on feedback |
| `gold.author` | write a gold answer for your own Q&A |

**Admin surface**

| Capability | Guards |
|---|---|
| `advanced.view` | see the Advanced page at all (the shell + the nav link) |
| `feedback.view` | Feedback tab |
| `golds.view` | Golds tab (read) |
| `golds.curate` | toggle *Incl.* on a gold |
| `golds.edit.own` | edit a gold **you authored** |
| `golds.edit.any` | edit **any** gold |
| `sources.view` | Sources tab (read) |
| `sources.curate` | toggle a source's inclusion |
| `sources.add` | upload a new source — **not yet in code** (lands with [`sources-upload.md`](sources-upload.md)) |
| `index.rebuild` | the *Rebuild Index* button |
| `users.manage` | Users tab: view rows, change roles, add/remove/rename invites |
| `roles.manage` | change the RBAC config itself (assign roles; later, edit bundles) |

Everything above except `sources.add` is defined in `roles.py` and enforced today.

Three deliberate coarseness / naming calls, all revisitable:

- **Names outlive labels.** The capability is `advanced.view` even though the HTTP
  route is still `/admin/*` and the page still reads "Admin" until the frontend relabel.
  Capability strings are stable identifiers; naming this one `admin.*` would leave an
  unmoored fossil once the page is renamed. Routes stay `/admin/*` (an internal
  management-API namespace, never shown on the page).

- **Users tab is one capability, not three.** The user floated "see the tab but not the
  TOKEN/ACTIONS columns or the role picker." That's real, but it multiplies the set
  fast. Ship `users.manage` as all-or-nothing first; split into
  `users.view` / `users.edit_roles` / `users.manage_invites` only when someone actually
  needs the middle ground.
- **`golds.edit.own` vs `golds.edit.any`** is the one place a capability isn't a pure
  role lookup — see §4.

## 3. Roles = capability bundles

Assignment is unchanged: a token still maps to **one role name** (seed ⊕ `roles.jsonl`
overrides, live-editable). What changes is that a role now resolves to a **set of
capabilities** instead of a rank.

The existing five map straight over with **no behaviour change** — this is the shipped
bundling:

| Role | Capabilities |
|---|---|
| `suspended` | *(none)* |
| `novice` | `ask`, `rate` |
| `evaluator` | + `feedback.annotate`, `gold.author` |
| `admin` | + the full Advanced surface: `advanced.view`, `feedback.view`, `golds.view`, `golds.curate`, `golds.edit.any`, `sources.view`, `sources.curate`, `index.rebuild` |
| `superuser` | + `users.manage`, `roles.manage` |

Two subtleties the code makes explicit:

- **`admin` does *not* get `users.manage` / `roles.manage`.** Today the Users tab and
  role changes are superuser-only (`/admin/invite-tokens` and `/admin/roles` are
  superuser-gated), so the bundling preserves that. The design's earlier "admin =
  everything except roles.manage" would additionally hand admin the Users tab — a real
  **policy** change. It's now a one-line move (drop `users.manage` into the admin bundle)
  **pending your call**; the mechanism swap deliberately didn't decide it.
- **`admin`/`superuser` hold `golds.edit.any`, not `golds.edit.own`.** `edit.any` already
  grants editing everything (§4), so the strictly-lesser "your own only" form is left for
  the curator tier — no role carries both.

The three new roles (names are placeholders — pick your own "cattle" labels). Every human
role builds on the public tier, so each can still `ask`/`rate`:

| Role | = | Capabilities |
|---|---|---|
| **`observer`** (#1) | read-only Advanced | `ask`, `rate`, `advanced.view`, `feedback.view`, `golds.view`, `sources.view` |
| **`curator-lite`** (#2) | observer + act on golds | + `golds.curate`, `index.rebuild` |
| **`curator`** (#3) | curator-lite + author | + `feedback.annotate`, `gold.author`, `golds.edit.own` |

Note what each role **can't** do, by construction: `observer` never sees the Users tab
(no `users.manage`), never rebuilds, never toggles *Incl.*; `curator` edits its own
answers but not others' (`golds.edit.own`, not `.any`). That's exactly the machinery
the ladder couldn't express. These three are defined and tested but **not yet offered in
the role picker** — the frontend slice turns them on.

## 4. The one resource-level check

Every capability except `golds.edit.own` is a pure `role → capability` lookup. `own`
needs one extra step: the gold row carries an `author`, and the edit is allowed only
when `author == current_guest`. So the check is:

```
can_edit_gold(user, gold) =
    has_capability(user.role, "golds.edit.any")
    or (has_capability(user.role, "golds.edit.own") and gold.author == user.id)
```

This is the bit that makes it *real* RBAC rather than a static table — the enforcement
point has to look at the resource, not just the role. Everything else stays a table.

> **Not yet enforced server-side.** The backend slice gates `POST /gold` on
> `gold.author` only; it does **not** yet check gold ownership, because there's a single
> authoring endpoint and no live role that has `edit.own`-without-`edit.any` (curator
> isn't assignable until the frontend slice). Wiring the ownership check onto `POST /gold`
> lands **with** the curator role, so the "can't edit others'" promise is real the moment
> the role is grantable — not before. Until then, `golds.edit.own`/`.any` shape the
> Golds-tab edit affordance in the UI.

## 5. Enforcement — backend and frontend read the same source

- **Backend.** ✅ **Done.** `require_capability(cap)` replaces `require_role(min)` at every
  endpoint; `ROLE_CAPABILITIES: dict[str, frozenset[str]]` + `has_capability(role, cap)`
  live in `roles.py`. Each endpoint names its capability (`/admin/rebuild-index` →
  `index.rebuild`, etc.). The gold ownership check (§4) is deferred to the curator slice.
- **`/me` returns the caller's capabilities.** ✅ **Done.** `capabilities: list[str]` is on
  the `/me` payload (sorted). This is the contract the UI renders against — the frontend
  must never hardcode "role X sees tab Y"; it asks "do I have `golds.curate`?" and shows
  the toggle or not.
- **Frontend.** ⏳ **Pending.** `AdminApp` renders each tab, column, and button behind a
  capability check; `App` shows the (renamed) nav link behind `advanced.view`. No rank
  math anywhere — the `ROLE_RANK` / `ROLE_LADDER_FALLBACK` constants retire.

One rule keeps backend and frontend honest: **the UI hides what you can't do; the
backend enforces it.** Hiding a button is UX, not security — the endpoint still checks
the capability, so a hand-crafted request is rejected the same way.

## 6. Where it's hardcoded vs. data-driven (first cut)

Start with `ROLE_CAPABILITIES` as a **literal in `roles.py`**. Adding or changing a role
is a code edit + deploy — fine at this scale, and it keeps the capability set and its
one-line meanings reviewable in the diff. Structure it so the *values* (the bundles) can
later move to a GCS-backed config exactly like `roles.jsonl`, without touching the
enforcement points. That migration is §7.

## 7. Later (NOT near-term): define & edit permissions from the UI

The end-state the user wants is managing the RBAC config as **data**: create a new role,
re-bundle capabilities, maybe define a new capability — all live, no deploy. Sketch, so
the phase-1 code doesn't paint us out of it:

- **Role bundles become data.** Move `ROLE_CAPABILITIES` into a GCS object
  (`role_defs.json`, same read-with-TTL pattern as roles/invites). A superuser
  (`roles.manage`) edits bundles in a new admin surface; assignment
  (`token → role`) is unchanged.
- **A capability registry.** The list in §2 becomes a declared registry (string +
  human description + which surface it guards) so the editor can render checkboxes with
  labels instead of raw strings.
- **The hard limit, stated plainly.** You can data-drive *which capabilities a role
  bundles*, but a capability only *does* something because **code checks it** at an
  enforcement point. "Define a brand-new permission from the UI" can register the string
  and bundle it, but it's inert until an endpoint/UI element guards on it. So the UI can
  safely **create roles and re-bundle existing capabilities**; **inventing new
  enforcement** stays a code change. Design the editor to make that boundary obvious
  (existing capabilities are pickable; new ones are "declared but unguarded" until
  wired).
- **Guardrails.** Can't delete a capability an endpoint still references; can't leave a
  token pointing at a deleted role (fall back to `DEFAULT_ROLE`); superuser can't strip
  their own `roles.manage` and lock everyone out.

## 8. Sequencing (and the AdminApp.tsx collision)

The frontend slice edits `web/src/AdminApp.tsx` — the same file the sortable-columns
session and the label-rename frontend touch. **The UI work waits until those PRs land**
to avoid a three-way conflict. Suggested order:

1. **Backend caps** — `ROLE_CAPABILITIES` + `has_capability` + `require_capability`;
   port every endpoint; ownership check for `.own`. Ladder roles behave identically, so
   this ships behind the existing UI with no visible change.
2. **`/me` carries `capabilities`.**
3. *(after sorting + rename land)* **Frontend gating** — tabs/columns/buttons by
   capability; retire `ROLE_RANK` / `ROLE_LADDER_FALLBACK`; add the three new roles to
   the role picker.
4. **Ownership UX** — show the edit control on golds only where §4 allows.
5. *(later)* **data-driven bundles**, then **the permissions editor** (§7).

## 9. Non-goals (first cut)

- Per-field ACLs beyond the one `own`/`any` split.
- Inventing new enforcement points from the UI (§7).
- Splitting `users.manage` into column-level pieces — deferred until needed.
