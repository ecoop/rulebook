# User roles (RBAC)

_Last updated: 2026-08-15_

> **This is the overview.** The authoritative references are
> [`rbac-capabilities.md`](rbac-capabilities.md) (the capability set and which
> level holds what) and [`rbac-data-driven-roles.md`](rbac-data-driven-roles.md)
> (capability-set fingerprints + the roadmap to editable, data-driven roles).
> [`users-tab.md`](users-tab.md) covers the admin UI. This file is the "what the
> role model is, and why" summary that ties them together.

Rulebook layers authorization on top of `guest-auth`: `guest-auth` answers *who
is this?*, rulebook answers *what may they do?*. Feedback, gold authoring, the
Advanced surface, and role changes themselves are all gated by what the caller
is allowed to do.

## The model as shipped

Authorization is **capability-based**. Endpoints gate on named capabilities via
`require_capability(cap)` — not on rank. A **role** is a named bundle of
capabilities; `/me` returns the caller's full bundle and the frontend renders
controls against it (the backend still enforces).

Roles are nine stable machine ids, `level0`…`level8`, each a strict superset of
the one below (Hierarchical RBAC / NIST). The numbers are stable keys; the
**display name** is a cosmetic label and the ordering is a display choice, not a
security boundary.

| id | name | what it adds (one-line) |
|---|---|---|
| `level0` | Suspended | No access |
| `level1` | Beginner | Ask and rate answers |
| `level2` | Annotator | Comment on answers |
| `level3` | Contributor | Suggest and revisit your own golds |
| `level4` | Builder | See the passages and sources behind answers |
| `level5` | Reviewer | Review everyone's work |
| `level6` | Director | Curate & clone golds, rebuild index, audit |
| `level7` | Admin | Users tab; change roles |
| `level8` | Superuser | Remove/rename users; RBAC config |

Names and descriptions live in one place — `ROLE_LEVELS` in
`src/rulebook/roles.py`, mirrored for presentation in `web/src/levels.tsx`. The
full capability-to-level matrix is in
[`rbac-capabilities.md`](rbac-capabilities.md).

### Capability-set fingerprint

Each role's capability set has an 8-hex **fingerprint** —
`sha256(",".join(sorted(caps)))[:8]` — an order-independent content address of
*what the role can do*, used for dedup / versioning / audit. It is **not** the
assignment key: assignments key on the stable `levelN` id, so relabeling or
re-tuning a level never orphans who is assigned to it. Details and roadmap:
[`rbac-data-driven-roles.md`](rbac-data-driven-roles.md).

## Role resolution — two sources

Merged per request:

1. **Seed** — `RULEBOOK_INITIAL_ROLES` (env), e.g. `{"tok_alice": "level7"}`.
   Baseline; requires a redeploy to change.
2. **Overrides** — live assignments in the GCS state object, written by the
   Users tab / `POST /advanced/roles`. Persist across restarts, no redeploy.

Effective role: `override(token) or seed(token) or "level1"`. `level1`
(Beginner) is the safe default for an authenticated-but-unassigned invite — they
can ask and rate, nothing more.

### Suspended (`level0`) — revocation as a role

Setting a user to `level0` gates every endpoint (including `/me`) → 403, while
their `guest-auth` cookie stays technically valid. Advantages of modeling
revocation as a role: reversible with one `POST /advanced/roles` call, no
redeploy to revoke or restore, and historical/audit rows keep their `author`
intact. Full removal (dropping the invite from the allowlist so the cookie stops
resolving) is a separate destructive op — `users.remove`, superuser-only.

### Bootstrap

At least one seed token must be `level8`. There is no self-promotion endpoint, by
design — same shape as `root`: the first superuser is baked in at deploy time, so
an admin can't grant themselves the keys and a demotion accident can't deadlock
recovery.

## Enforcement

`require_capability(cap)` is a FastAPI dependency: resolve the caller's role → its
capability set → 403 if `cap` is absent. In **public mode** (`demo_mode` off) the
base tier stays open (anonymous `/ask`, rating) but everything on the Advanced
surface fails closed.

Representative gates (full matrix in [`rbac-capabilities.md`](rbac-capabilities.md)):

| Surface | Capability | Lowest level |
|---|---|---|
| ask, rate, revisit your own | `ask`, `rate`, `activity.view`, `feedback.view` | level1 |
| comment on an answer | `feedback.comment` | level2 |
| suggest & revisit your own golds | `gold.author`, `golds.view`, `golds.edit.own` | level3 |
| passages + Sources tab, own items | `advanced.view`, `passages.view`, `sources.view` | level4 |
| review everyone's items (with authors) | `feedback.view.all`, `golds.view.all`, `questions.view.all` | level5 |
| curate / clone / rebuild / audit | `golds.curate`, `golds.clone`, `index.rebuild`, `attribution.view` | level6 |
| Users tab, change role, add invitee | `users.view`, `users.change_role`, `users.add` | level7 |
| remove / rename user, RBAC config | `users.remove`, `users.rename`, `roles.manage` | level8 |

Non-permitted controls are **hidden, not disabled** — "you only see what you can
do." Gating is active only in `demo_mode`; a local / dev deploy keeps full
features.

## Self vs all — scoping

Questions, golds, and feedback lists are scoped to the caller's own rows unless
they hold the matching `*.view.all` capability (level5+), which also reveals **who**
wrote/asked each row — authorship rides with the all-view tier, not a separate wall
(we don't do blind review). `attribution.view` (level6) is now just the Audit tab.
Curation and cloning key on `gold_id`; a user with `golds.clone` (level6) forks
another's gold into a new one they own rather than editing it in place — there is no
`golds.edit.any`.

## Audit trail

Every shared-state mutation (role change, gold curation, index rebuild, user
add / remove / rename) appends a row to `audit.jsonl` — actor, action, target,
detail, and the actor's capability-set fingerprint at the time. Readable via
`GET /advanced/audit`, gated on `attribution.view` (level6+). This was a non-goal
in the original design; it now ships.

## `/me`

`GET /me` (any authenticated caller) returns
`{recipient, role, level, capabilities, fingerprint, demo_mode}` — the contract
the frontend renders tabs / columns / buttons against. Note it is fetched once on
load, so a role change mid-session does not hot-swap the UI yet (tracked in
[#42](https://github.com/ecoop/rulebook/issues/42)).

## Non-goals

Still out of scope:

- Group-based roles.
- Time-bounded grants ("admin for 24 hours").
- Automated promotion (e.g. Beginner → Contributor after N ratings) — the
  `/advanced/roles` path could drive it later without changing the model.
- Self-service downgrade (a footgun on a single-superuser system; a superuser
  demoting themselves would deadlock the bootstrap).

**Delivered since the original design** — no longer non-goals: fine-grained
per-capability permissions (that *is* the capability model), and an audit trail
beyond the append-only role log.

## History

This document originally specified a monotonic **four-tier** ladder
(`suspended` / `novice` / `evaluator` / `admin` / `superuser`) gated by
`require_role(min)` under `/admin/*`. That shipped, then was generalized: the
tiers became the nine `levelN` capability bundles, `require_role` became
`require_capability`, `/admin/*` became `/advanced/*`, and the frontend gating +
superuser Users tab were built. The still-valid design rationale — revocation as
a role, the Admin (`level7`) / Superuser (`level8`) split to avoid self-promotion
and bootstrap deadlock, hide-not-disable, two-source resolution — carried
forward above. See the git log and the two `rbac-*.md` docs for the capability
model and the data-driven-roles plan.
