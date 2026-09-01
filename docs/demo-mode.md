# Demo mode on Cloud Run

_Last updated: 2026-08-27_

**Implemented and live** at <https://rulebook.cooper.nu>. The capability-based
RBAC backend, a GCS-backed live-editable invite allowlist, frontend gating, and
the Users tab all shipped. This is the operator runbook.

## How it works

- **Gate:** `RULEBOOK_DEMO_MODE=true`. Off → no auth (local dev unchanged).
  Guests visit `?token=…` → httpOnly `Secure` cookie → clean-URL redirect.
- **Invite allowlist `{token: label}` — two sources merged per request:** env
  seed `RULEBOOK_INVITE_TOKENS` ⊕ a **live GCS object**
  (`RULEBOOK_INVITE_TOKENS_OBJECT`, default `invite_tokens.json`) read with a
  ~30s TTL when `STATE_BACKEND_KIND=gcs`. So **adding/removing invitees is
  redeploy-free**.
- **Roles (authZ):** capability-based — `RULEBOOK_INITIAL_ROLES` seed ⊕ live
  `roles.jsonl` (`RULEBOOK_ROLES_OBJECT`). Roles are the numbered levels
  `level0` (suspended) … `level8` (superuser); each is a bundle of capabilities,
  and endpoints gate on `require_capability(...)`, not role names (see
  [roles.md](roles.md), [rbac-capabilities.md](rbac-capabilities.md)).
  Unassigned tokens default to `level1`. Promote/demote/suspend is live via
  `POST /advanced/roles` — no redeploy — as is per-user **domain scoping** via
  `/advanced/allowed-domains` (which domains a user may ask against; Admin/
  Superuser are unscoped).

## Managing invitees (live, no redeploy)

From the **Users** tab ([users-tab.md](users-tab.md)), or `scripts/invite_tokens.py`:

```bash
uv run python -m scripts.invite_tokens list
uv run python -m scripts.invite_tokens add "Alice"          # mints tok_...
uv run python -m scripts.invite_tokens add "Bob" --token tok_custom
uv run python -m scripts.invite_tokens rm tok_abc123
```

Needs `STATE_BACKEND_KIND=gcs`, `GCS_STATE_BUCKET`, and ADC (`gcloud auth
application-default login`). Share links as `https://rulebook.cooper.nu/?token=<tok>`.

**Repurposing a token's label** (e.g. an unused invite → a new person): fine when
unused. If the token was *used*, the new name inherits its weekly cost, an
existing cookie keeps resolving to it, and past log rows keep the old label —
mint a fresh token and suspend the old one (set role `level0`) instead.

## Deploy config (Cloud Run)

- `STATE_BACKEND_KIND=gcs`, `GCS_STATE_BUCKET=…` — index, logs, cost counter,
  allowlist, roles, and the **rule source docs** all live in the bucket and sync
  into the container at runtime (the image ships no state; rule PDFs sync via
  `rules_sync`, #170).
- `RULEBOOK_DEMO_MODE=true`.
- **Bootstrap a superuser** (only way to seed the first one):
  `RULEBOOK_INITIAL_ROLES='{"tok_you":"level8"}'`. (Use the level id — a bad
  role id like `"superuser"` resolves to *no* capabilities, fail-closed, and the
  seeded user gets locked out.)
- `--max-instances=1` — the cost counter is per-instance in-memory; more
  instances under-count caps.
- Keep seed roles/tokens in **Secret Manager → env** (`--set-secrets`), never
  baked into the image. HTTPS (for `Secure` cookies) is provided by Cloud Run.
- Deploy with `./scripts/deploy.sh` (targets your own Cloud Run project via `RULEBOOK_PROJECT`).

## Host

Live: <https://rulebook.cooper.nu> — CNAME → `ghs.googlehosted.com`, HTTPS with valid cert.
