# Users tab — reference

_Last updated: 2026-11-23_

The **Users** tab (in the "Your activity" view, `web/src/ActivityApp.tsx`)
manages invitees, their roles, and their domain access. **Shipped** — this is
the as-built reference (the earlier frontend build-spec is superseded).

## Three concepts (don't conflate)

- **Allowlist** = *who can log in* (invite tokens) → `/advanced/invite-tokens`.
- **Role** = *what a logged-in user may do* (a bundle of capabilities) → `/advanced/roles`.
- **Domain scope** = *which domains they may ask against* → `/advanced/allowed-domains`
  (#112/#156). Admin/Superuser (level ≥ 7) are unscoped.

Creating a user = add to the allowlist (+ optionally set a role and domains).
Removing access: **suspend** (reversible — set role `suspended`, keeps audit) vs
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
| GET | `/advanced/join-requests` | `requests.view` |
| POST | `/advanced/join-requests/{id}/approve` | `requests.decide` |
| POST | `/advanced/join-requests/{id}/decline` | `requests.decide` |
| POST | `/advanced/join-requests/purge` | `requests.purge` |
| GET | `/advanced/join-settings` | `requests.view` |
| PUT | `/advanced/join-settings` | `requests.configure` |
| POST | `/advanced/join-settings/test-email` | `requests.configure` |

`ladder` (from `/advanced/roles`, low→high): `["suspended", …, "superuser"]`
(suspended = suspended, superuser = superuser). Reset clears an override → default
`beginner`. 409 on a duplicate token; 404 removing an unknown one.

## Join requests (#337)

People without an invite ask to join; an admin approves or declines them in the
**Requests** tab, beside Users (`web/src/RequestsTab.tsx`; its label shows the
waiting count). A request is only a record (`join_requests/<id>.json` in the state bucket): no user exists
until it's approved.

- **Approve** creates the user through the same path as add-user: a minted
  token, an explicit domain grant, and (unlike add-user) an explicit role row.
  Role and domains default to the join settings and can be changed per request;
  the label defaults to the requester's name and must not match an existing
  label (409). 409 if the request was already decided.
- **Decline** keeps the record, name and email included, for audit.
- **Purge** (superuser) permanently deletes every declined request. Its audit
  row records only the count.
- **Join settings** (`join_settings.json`): `mode` = `closed` (default) /
  `referral-only` / `open`; `pending_cap` (public requests stop at this many
  waiting; referrals aren't capped); `default_role` (`beginner`) and
  `default_domains` (`["goaltimate"]`) for approval.
- **Email**: a new request emails `RULEBOOK_NOTIFY_EMAIL` (default: the SMTP
  user) over SMTP/STARTTLS, Gmail by default. Configure `RULEBOOK_SMTP_USER`
  and `RULEBOOK_SMTP_PASSWORD` (a Gmail app password, from Secret Manager);
  optionally `RULEBOOK_PUBLIC_URL` for a link to this tab. Unset = no email.
  The test-email endpoint checks the setup.
- **Not yet**: the public form and its endpoints (`GET /join/status`,
  `POST /join`) need guest-auth's public paths; they come in part 2.

## Gotchas

- Changes propagate within the source TTL (~30s) across instances; immediate on
  the instance that served the write.
- Minted tokens are opaque (`tok_…`); the label is the human identity.
- A role (or domain grant) with no allowlist entry can't log in — manage both.
