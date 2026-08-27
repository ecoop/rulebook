# Users tab — reference

_Last updated: 2026-08-27_

The **Users** tab (in the "Your activity" view, `web/src/ActivityApp.tsx`)
manages invitees, their roles, and their domain access. **Shipped** — this is
the as-built reference (the earlier frontend build-spec is superseded).

## Three concepts (don't conflate)

- **Allowlist** = *who can log in* (invite tokens) → `/advanced/invite-tokens`.
- **Role** = *what a logged-in user may do* (a bundle of capabilities) → `/advanced/roles`.
- **Domain scope** = *which domains they may ask against* → `/advanced/allowed-domains`
  (#112/#156). Admin/Superuser (level ≥ 7) are unscoped.

Creating a user = add to the allowlist (+ optionally set a role and domains).
Removing access: **suspend** (reversible — set role `level0`, keeps audit) vs
**remove** (hard delete from the allowlist).

## API

Capability-gated (403 otherwise; 400 if the deploy isn't GCS-backed). `/me`
returns the caller's `{recipient, role, level, fingerprint, capabilities,
allowed_domains, demo_mode}`; the UI gates on **capabilities** (e.g.
`users.view`), not a role name.

| Method | Path | Capability |
|---|---|---|
| GET | `/advanced/invite-tokens` | `users.view` |
| POST | `/advanced/invite-tokens` | `users.add` |
| PATCH | `/advanced/invite-tokens/{token}` | `users.rename` |
| DELETE | `/advanced/invite-tokens/{token}` | `users.remove` |
| GET | `/advanced/roles` | `users.view` |
| POST | `/advanced/roles` | `users.change_role` |
| POST | `/advanced/roles/{token}/reset` | `users.change_role` |
| GET | `/advanced/allowed-domains` | `users.view` |
| POST | `/advanced/allowed-domains` | `users.change_role` |
| POST | `/advanced/allowed-domains/{token}/reset` | `users.change_role` |

`ladder` (from `/advanced/roles`, low→high): `["level0", …, "level8"]`
(level0 = suspended, level8 = superuser). Reset clears an override → default
`level1`. 409 on a duplicate token; 404 removing an unknown one.

## Gotchas

- Changes propagate within the source TTL (~30s) across instances; immediate on
  the instance that served the write.
- Minted tokens are opaque (`tok_…`); the label is the human identity.
- A role (or domain grant) with no allowlist entry can't log in — manage both.
