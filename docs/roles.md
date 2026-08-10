# User roles (RBAC)

_Last updated: 2026-08-10_

Design doc — not yet implemented. Captures the planned role model layered on top of `guest-auth`, so `feedback`, `gold`, admin actions, and role changes themselves are gated by what the caller is allowed to do.

## Why

`guest-auth` currently answers _who is this?_ (authentication) but not _what can they do?_ (authorization). Every valid guest has the same access — they can ask, rate, write notes, author golds, reach the admin panel, everything.

That's fine for a small trusted circle. It stops being fine when:

- We invite people who should be able to _rate_ answers but not _author gold_ ones.
- We want to demote or promote a user in real time without redeploying.
- We want a clean bootstrap path — someone has to be able to grant privileges without granting them to themselves.

## Scope

- Small, monotonic role ladder (four tiers).
- Code-defined permission matrix — no per-resource ACL.
- Live role changes (no redeploy required).
- Bootstrap via env var; day-to-day changes via API.

**Not** in scope: group-based roles, time-bounded grants, per-endpoint fine-grained permissions, audit trail beyond the append-only role log.

## Roles

Monotonic ladder — each role gets everything the one below has, plus one thing more.

| Role | Ask | Rate (1–5) | Tags / Notes | Gold answer | Admin panel | Change roles |
|---|---|---|---|---|---|---|
| `novice` | ✓ | ✓ | | | | |
| `evaluator` | ✓ | ✓ | ✓ | ✓ | | |
| `admin` | ✓ | ✓ | ✓ | ✓ | ✓ | |
| `superuser` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

Monotonic ordering matters — `require_role(min)` becomes a single comparison rather than a set-membership check.

### Rationale for the split

- **novice / evaluator** — the promotion path. Novice contributions (bare ratings) are the cheapest useful signal; evaluator adds the richer surface (tags, notes, gold answers) that requires more judgment. Automated promotion criteria (e.g. "novice → evaluator after N ratings") can layer on later without changing the model.
- **admin** — access to the curation surface (Feedback / Golds / Sources tabs, Rebuild index button). Not the same population as evaluators; a domain expert who evaluates well isn't necessarily who curates the corpus.
- **superuser** — separated from admin specifically to avoid the "everyone with admin can promote themselves" foot-gun. Also solves the bootstrap deadlock: if there were no superuser, an admin who accidentally demoted every other admin couldn't recover.

## Where role lives — split concerns

- **`guest-auth` (upstream)** — stays as-is. Owns identity (`token`, `recipient`). Authentication only. Reusable across projects with different role vocabularies.
- **`rulebook` (downstream)** — owns role. Authorization. Rulebook-specific vocabulary, doesn't leak into `guest-auth`.

This matches the classic authN / authZ split. Pitchcraft and jobscout can layer their own role models on top of the same `guest-auth` without either project's roles bleeding into the shared library.

## Role resolution — two-source model

Two sources merged at request time:

1. **Env-var seed** — `RULEBOOK_INITIAL_ROLES` = `{"tok_alice": "admin", "tok_bob": "superuser"}`. Baseline. Requires redeploy to change.
2. **Mutable overrides** — `roles.jsonl` (append-only, latest-per-token wins). Written by the superuser API. Persists across restarts.

Effective role at request time:

```
overrides.get(token) or seed.get(token) or "novice"
```

Novice as the safe default catches an authenticated-but-unassigned token — someone whose invite works but whose role hasn't been set. They can ask questions and rate; nothing else.

### Bootstrap

At least one token in `RULEBOOK_INITIAL_ROLES` must be `superuser`. Documented as the only way to seed the first superuser — no self-promotion endpoint exists, deliberately. Same shape as `root` on Unix: someone has to be able to grant, and that someone has to be baked in at deploy time.

## API surface

Three endpoints under `/admin/roles`, all `superuser`-gated:

- `GET /admin/roles` — current role assignments (seed + overrides merged).
- `POST /admin/roles` — body: `{token, role}`. Appends to `roles.jsonl`.
- `DELETE /admin/roles/{token}` — appends a "reset-to-seed" marker; next resolve falls back to the seed value (or novice if not seeded).

Plus one public-ish endpoint any authenticated user hits:

- `GET /me` — returns `{recipient, role}` for the current guest. Powers frontend UI gating.

## Enforcement

FastAPI dependency factory:

```python
def require_role(minimum: Role) -> Callable:
    def _check(request: Request):
        guest = get_current_guest()
        if not guest or resolve_role(guest.token) < minimum:
            raise HTTPException(403)
    return _check
```

Applied at endpoint declarations:

| Endpoint | Minimum role |
|---|---|
| `/ask` | novice |
| `/feedback` | novice (partial — see below) |
| `/gold` | evaluator |
| `/usage`, `/diagnostics`, `/meta`, `/me` | novice |
| `/admin/golds`, `/admin/sources`, `/admin/feedback`, `/admin/rebuild-index` | admin |
| `/admin/gold-curation`, `/admin/source-curation` | admin |
| `/admin/roles*` | superuser |

### The `/feedback` partial-permission case

`/feedback` accepts three fields — `rating`, `tags`, `comment`. Novices are allowed to submit `rating` but not `tags` or `comment`. Two ways to enforce:

- **Two endpoints** — `/feedback/rating` (novice+) and `/feedback/full` (evaluator+). Clean but adds surface.
- **One endpoint with body-level validation** — reject requests where `tags` / `comment` are present and the caller is below `evaluator`. Simpler; matches the fact that both flows land the same jsonl row shape.

Recommendation: **body-level validation**, single endpoint. Return 403 with a specific error message pointing at the field that requires evaluator role.

## UI role awareness

Frontend fetches `/me` on load; component tree branches on `role`.

- **novice**: rating pips + submit only. Tag chips hidden, note textarea hidden, "Save gold answer" button hidden.
- **evaluator**: current full HITL surface.
- **admin**: also renders the `admin` link in the footer.
- **superuser**: admin page gets a new "Roles" tab (list users, promote / demote / reset).

Non-permitted controls are **hidden**, not disabled. Disabled controls confuse novices about what's available; hiding matches "you can only see what you can do."

## Durability of `roles.jsonl`

Same problem the other logs face: local disk in the container is ephemeral. Two paths:

- **Wait for `jsonl-log` v0.2** — the durability plan already in flight. Clean, consistent with feedback/gold logs.
- **Stopgap: direct-to-GCS for roles specifically** — roles are tiny (dozens of entries), rarely change (weekly at most), and a lost role change is a real UX regression (worse than losing a feedback row). A bespoke ~30-line "rewrite one small GCS object per change" is defensible and unblocks live role management from day one, independently of `jsonl-log`.

Recommendation: **stopgap**. Losing a role change on restart is disproportionately bad, and the volume is so low that a custom write is trivial to maintain until `jsonl-log` v0.2 lands and can absorb the pattern.

## Non-goals

- Per-endpoint fine-grained permissions beyond the four-tier ladder.
- Group-based roles.
- Time-bounded role grants ("admin for 24 hours").
- Audit trail beyond the append-only `roles.jsonl` itself.
- UI for a role-holder to voluntarily downgrade themselves (footgun on a single-superuser system; superuser demoting themselves would deadlock the bootstrap).
- Automated novice → evaluator promotion. Planned for later; the API can support it via the same `POST /admin/roles` path, driven by a small background evaluator.

## Prerequisites

- `guest-auth` — no changes needed. Cleanest of everything.
- `jsonl-log` v0.2 — nice-to-have for `roles.jsonl` durability via the same path as other logs. Not strictly required; the stopgap ships without it.
- Per-guest cost cap wiring (`caller_weekly_usd`) — already in place from Track A.

## Implementation order (not a promise, a sketch)

1. Endpoint stubs + `require_role` dependency, gating everything at novice for now (identical to current behavior). No UI change.
2. `RULEBOOK_INITIAL_ROLES` env-var support + `resolve_role()` reading from the seed only. Tags/notes/gold guarded at evaluator; admin surface at admin.
3. `roles.jsonl` overrides + superuser API endpoints.
4. `GET /me` endpoint + frontend UI gating.
5. Durable backend for `roles.jsonl` (stopgap GCS write, or wait for `jsonl-log` v0.2).
