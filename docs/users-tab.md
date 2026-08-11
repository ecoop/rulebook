# Users tab — frontend build spec

_Last updated: 2026-08-10_

Backend for the superuser **Users** tab is implemented and deployed (see
[roles.md](roles.md), `rulebook.tokens`, `rulebook.roles`). This is the
handoff spec for the **frontend** piece, which lands in `web/src/AdminApp.tsx`
and must be built on top of the Pitchcraft-parity restyle (PR #19) — not on
`main` — so it inherits the new tab chrome and semantic tokens.

## Where it slots

`AdminApp.tsx` already has an `activeTab` model (`feedback | golds | sources`)
with a `refresh<Tab>()` fetch per tab. Add a `roles` / `users` tab the same
way: one more `AdminTab` value, one `refreshUsers()`, one table + a small
"Add user" form. Match the existing fetch/error/pending-set patterns.

## Two backend concepts (don't conflate)

- **Allowlist** = *who can log in* (invite tokens). `/admin/invite-tokens`.
- **Role** = *what a logged-in user may do*. `/admin/roles`.

Creating a user = add to the allowlist (+ optionally set a role). Removing
access has two flavors: **suspend** (reversible, keeps audit — set role
`suspended`) vs **remove** (hard delete from the allowlist).

## API (all superuser-gated; 403 otherwise, 400 if the deploy isn't GCS-backed)

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/me` | — | `{recipient, role, demo_mode}` — gate the whole tab on `role === "superuser"` |
| GET | `/admin/invite-tokens` | — | `{tokens: [{token, label}]}` |
| POST | `/admin/invite-tokens` | `{label, token?}` | `{token, label}` — mints if `token` omitted |
| DELETE | `/admin/invite-tokens/{token}` | — | `{ok, token, label}` |
| GET | `/admin/roles` | — | `{roles: [{token, role, source}], ladder}` |
| POST | `/admin/roles` | `{token, role, note?}` | `{ok, token, role}` |
| POST | `/admin/roles/{token}/reset` | — | `{ok, token, role}` — clears override → seed/novice |

`ladder` (low→high): `["suspended","novice","evaluator","admin","superuser"]`.
409 on adding a duplicate token; 404 removing an unknown one.

## Suggested UX

1. **Table** — join `/admin/invite-tokens` (label, token) with `/admin/roles`
   (role, source) keyed by token. Columns: Label · Token (truncated, click to
   copy) · Role (a `<select>` of `ladder`) · Source (seed/override) · actions.
2. **Add user** — text field (label) + "Add". On success, show the invite
   link `https://<host>/?token=<token>` with a copy button (that URL exchanges
   the token for the session cookie).
3. **Role change** — the `<select>` calls `POST /admin/roles`; a "Reset"
   action calls the reset route; "Suspend" is just setting role `suspended`.
4. **Remove** — a destructive "Remove" that calls DELETE; confirm first, and
   nudge toward Suspend for reversible blocks.
5. Non-superusers never see the tab (`/me`). Show a friendly note if
   `demo_mode` is false (management needs the gated deploy).

## Gotchas

- Changes propagate within the source TTL (~30s) across instances; immediate
  on the instance that served the write.
- Minted tokens are opaque (`tok_…`); the label is the human identity.
- Don't build user creation on `/admin/roles` alone — a role with no
  allowlist entry can't log in.
