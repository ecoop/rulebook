# Roles as permission-sets — design note + plan

_Last updated: 2026-08-12_

> **Status: design note, not scheduled.** Deepens the "define/edit permissions from the
> UI" sketch in [`rbac-capabilities.md`](rbac-capabilities.md) §7–§8 with a concrete
> framing that came out of naming the roles: **a role is its set of permissions; the name
> is a sticker.** Captures the direction so the current (hardcoded, level-named) code
> doesn't paint us out of it.

## The idea

Stop treating a role's **name** or **order** as load-bearing. A role *is* a set of
capabilities; everything else is presentation. Split it into three (four) separable things:

| Concern | What it is | Mutable? | Example |
|---|---|---|---|
| **id** | the assignment handle — `token → role` stores this | **stable, never reused** | `level4`, a slug, a uuid |
| **capability set** | the actual permissions — the *truth* | editable | `{advanced.view, golds.edit.own, …}` |
| **label** | the display name | swappable freely, anytime | "Builder" |
| *(fingerprint)* | `hash(sorted(capabilities))` | derived | dedup / version / audit |

Once these are independent, the entire naming thread (Beginner vs Annotator, "is it
ordered?", "what goes between 5 and 6?") becomes a **display** question with no bearing on
identity, enforcement, or stored assignments.

## Why

- **Rename / reorder freely, zero migration** — the label never touches the id or the
  seed/`roles.jsonl`.
- **Re-tuning a role's capabilities doesn't reassign anyone** — the id is stable; only the
  set behind it changes.
- **On-ramp to UI-defined roles** — a superuser assembles a capability set, the system
  mints a stable id, they attach a label. No ladder, no renumbering.

## The hash: a fingerprint, not the key

The instinct to "hash the permissions and use that" is right *as a fingerprint*, wrong *as
the assignment key*:

- **As a fingerprint — do it.** `sha256(sorted(caps))[:8]` content-addresses a bundle:
  dedupe identical roles, detect "did this role's powers change?", and stamp audit rows
  with the exact permission-set version in force at the time. Cheap, no downside.
- **As the assignment key — don't.** If a role's identity *is* the hash of its caps, then
  **editing its capabilities changes the hash and orphans every token pointing at the old
  one.** Content-addressing forces immutability. Keep a small *stable, arbitrary* id for
  assignment (its only job is to be stable); let the hash be derived.

## Current state (already most of the way there)

- `ROLE_CAPABILITIES` (`src/rulebook/roles.py`) — a hardcoded map `level0…level8 →
  frozenset[capability]`. The ids are **already stable and arbitrary** (nothing depends on
  "level4" meaning anything).
- `ROLE_LEVELS` (`roles.py`) + `web/src/levels.tsx` — color + description (+ provisional
  names). This is the **label** layer.
- Assignment — seed (`RULEBOOK_INITIAL_ROLES`) + `roles.jsonl` store `token → id`.

So the three concerns exist; they're just (a) hardcoded and (b) the id and label happen to
coincide (`level4`). The plan makes them fully independent, then data-driven.

## Plan (phased)

**Phase 0 — done.** Capability mechanism (`require_capability`, `ROLE_CAPABILITIES`,
`has_capability`), hardcoded 8-rung bundles, display labels + colors + badge.

**Phase 1 — clean separation + fingerprint** *(small, backend-only, no behaviour change)*
- Treat the **label** as fully separate from the id: badge/picker read `ROLE_LEVELS[id].label`;
  the id is opaque. (Mostly true already — this just makes it explicit and drops any
  remaining "name implies order" assumptions.)
- Add `role_fingerprint(id) -> str` = `sha256(sorted(caps))[:8]`. Surface it in `/me`,
  `/advanced/roles`, and each audit row, so "this role's permissions changed on <date>" is
  answerable. Derived; nothing else changes.

**Phase 2 — roles become data** *(the §7 move)*
- Move `ROLE_CAPABILITIES` from a code literal to a GCS object (`role_defs.json`), same
  read-with-TTL pattern as `roles.jsonl`; seed the defaults from code on first run.
- `is_valid_role` / `capabilities_for` read the data-backed map.
- A `roles.manage` superuser can create / edit / label / retire bundles **live** (no deploy).
- Guardrails: a bundle can't reference an undeclared capability; a token pointing at a
  deleted id falls back to `DEFAULT_ROLE`; a superuser can't strip their own `roles.manage`
  and lock everyone out; at least one superuser id and `DEFAULT_ROLE` stay undeletable.

**Phase 3 — permissions-editor UI**
- A superuser "Roles" surface: checkbox a **capability registry** (each capability = string
  + description + which surface it guards) → mint a **stable id** (slug or hash-derived) →
  set label + color. Creating a bundle = a new id; editing an existing role's caps keeps its
  id, so **assignments never break**.

**The hard limit (unchanged from §7):** a capability only *does* something because **code
checks it** at an enforcement point. The UI can **create roles and re-bundle existing
capabilities**; **inventing new enforcement** stays a code change. Capabilities that are
declared but not yet guarded by any endpoint/UI are inert — the editor should mark them so.

## Non-goals / cautions

- **Don't** make the assignment key the permission-hash (the immutability trap above).
- **Don't** let the UI mint capabilities no endpoint enforces without flagging them as
  inert (declared-but-unguarded).
- Keep `DEFAULT_ROLE` and at least one superuser id un-deletable (bootstrap safety).

## Relation to the numbered-levels question

This dissolves it. With ids stable + arbitrary and labels cosmetic, whether roles are
"ordered" is purely a display choice — sort by label, by an optional `sort_key`, or not at
all. Inserting a tier "between 5 and 6" is just *a new id + bundle + label*; nothing
renumbers, nothing reassigns. So the current provisional names
(Beginner/Annotator/Contributor/Builder/Reviewer/Director/Admin/Superuser over
`level0…level8`) can settle whenever — they're never the thing that matters.
