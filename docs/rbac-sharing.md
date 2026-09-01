# RBAC sharing — guest-auth and consuming apps

_Last updated: 2026-08-31_

How authn/authz should layer across apps that build on guest-auth, and what (if anything) to extract.

## guest-auth — now
- Authn: invite token → cookie session (`InviteAuthMiddleware`).
- Identity: `GuestIdentity{token, recipient}`, via `get_current_guest()`.
- No roles, no permissions.

## guest-auth — broadened (small)
Add **claims** to the identity. guest-auth defines the *structure*, not the *meaning*.
- Identity gains typed fields: `GuestIdentity{token, recipient, role: str|None, scopes: list[str]|None}`.
- Manages the **association** token ↔ (role, scopes): store/resolve + attach per request
  (pluggable resolver so storage stays swappable).
- Value-agnostic: any string is a role, any strings are scopes. guest-auth never interprets
  or enforces them — that's policy, and policy lives elsewhere.

## Stays in Rulebook (as-is)
- Capability vocab: `CAP_ASK`, `CAP_INDEX_REBUILD`, … (~27).
- Role→caps bundles: `_R1.._R8` cumulative + `ROLE_LADDER`.
- Enforcement: `require_capability(cap)` FastAPI dep (~27 sites).
- Claim stores/resolution: `resolve_role` (roles.jsonl), `resolve_allowed_domains`, reset
  sentinel → become the resolver guest-auth calls.
- Scope meaning: "domains" = rulesets.

## Replicate in a second app (port, don't share yet)
- Same shapes, own policy:
  - own capability vocab (`deck.publish`, `billing.view`, …),
  - own role→caps bundles + ladder,
  - own scope meaning (workspaces/decks, not domains).
- Same `require_capability` dep; same resolver feeding guest-auth's claims.
- Reuse unchanged: guest-auth, llm-cost-governor, jsonl-log.

## Extract — once a second app is the 2nd consumer (rule of three)
- **Generic** (identical both sides): `require_capability` dep, `has_capability`, ladder
  ordering, the bundle *mechanism* (cumulative + reset sentinel), `in_scope(scope, resource)`.
- **Never extracted** (app policy): capability vocab, role names, scope meaning.
- **Homes:**
  - claims (role/scopes on identity, + resolver) → **guest-auth**.
  - policy engine (`require_capability` + bundle mechanism) → **`guest-auth[rbac]` extra**.

## New library? No.
- Ship the policy engine as a `guest-auth[rbac]` extra, not a 4th package: ~1 module, only
  meaningful atop guest-auth's identity, and a new repo/release cadence isn't worth it.
- Promote to standalone only if something ever needs the policy engine *without* guest-auth
  identity (unlikely).

## The line
- **guest-auth** — who are you + what claims you carry (role, scopes): structure, not meaning.
- **`guest-auth[rbac]`** — given those claims, may you do X.
- **app** — the capability vocab + role→caps + scope meaning.
