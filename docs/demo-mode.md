# Demo mode on Cloud Run

_Last updated: 2026-08-11_

**Mostly implemented.** The RBAC backend and a GCS-backed, live-editable invite allowlist shipped in #18; the demo is live at <https://rulebook.cooper.nu>. This is the operator runbook plus the short list of what's left (frontend gating / Users tab, web lane).

## How it works (shipped in #18)

- **Gate:** `RULEBOOK_DEMO_MODE=true`. Off → no auth (local dev unchanged). Guests visit `?token=…` → httpOnly `Secure` cookie → clean-URL redirect.
- **Invite allowlist `{token: label}` — two sources merged per request:** env seed `RULEBOOK_INVITE_TOKENS` ⊕ a **live GCS object** (`RULEBOOK_INVITE_TOKENS_OBJECT`, default `invite_tokens.json`) read with a ~30s TTL when `STATE_BACKEND_KIND=gcs`. So **adding/removing invitees is redeploy-free** — this is what [#20](https://github.com/ecoop/rulebook/issues/20) (Option C) planned, now shipped.
- **Roles (authZ):** `RULEBOOK_INITIAL_ROLES` seed ⊕ live `roles.jsonl` (`RULEBOOK_ROLES_OBJECT`). `require_role` gates endpoints per [roles.md](roles.md): novice for `/ask` `/feedback` `/usage` `/diagnostics` `/meta` `/me`; evaluator for `/gold`; admin for `/admin/*`; superuser for `/admin/roles*`. Unassigned tokens default to `novice`. **Promote/demote/suspend is live** via `POST /admin/roles` — no redeploy.

## Managing invitees (live, no redeploy)

`scripts/invite_tokens.py` writes the GCS allowlist object:

```bash
uv run python -m scripts.invite_tokens list
uv run python -m scripts.invite_tokens add "Alice"          # mints tok_...
uv run python -m scripts.invite_tokens add "Bob" --token tok_custom
uv run python -m scripts.invite_tokens rm tok_abc123
```

Needs `STATE_BACKEND_KIND=gcs`, `GCS_STATE_BUCKET`, and ADC (`gcloud auth application-default login`). Share links as `https://rulebook.cooper.nu/?token=<tok>`.

**Repurposing a token's label** (e.g. an unused invite → a new person): fine when unused. If the token was *used*, the new name inherits its weekly cost, an existing cookie keeps resolving to it, and past log rows keep the old label — mint a fresh token and `suspended` the old one instead. Tooling should challenge (warn, not block) a used-token rename — see [#20](https://github.com/ecoop/rulebook/issues/20).

## Deploy config (Cloud Run)

- `STATE_BACKEND_KIND=gcs`, `GCS_STATE_BUCKET=…` — index, logs, cost counter, allowlist, and roles persist across instances (image ships no state).
- `RULEBOOK_DEMO_MODE=true`.
- **Bootstrap a superuser** (only way to seed the first one): `RULEBOOK_INITIAL_ROLES='{"tok_you":"superuser"}'`.
- `--max-instances=1` — the cost counter is per-instance in-memory; more instances under-count caps.
- Keep seed roles/tokens in **Secret Manager → env** (`--set-secrets`), never baked into the image. HTTPS (for `Secure` cookies) is provided by Cloud Run.

## Remaining work (web lane)

- **Frontend role-gating** ([roles.md](roles.md) step 4): fetch `/me`, hide admin link / tags / notes / gold by role; `suspended` → no app shell. Depends on #19 merging first.
- **Users tab:** superuser UI over `/admin/roles` + the invite write-path ([users-tab.md](users-tab.md)).
- **Option C polish** ([#20](https://github.com/ecoop/rulebook/issues/20)): explicit label-edit + used-token challenge in the CLI.

## Host

Live: <https://rulebook.cooper.nu> — CNAME → `ghs.googlehosted.com`, HTTPS with valid cert. DNS/hosting lane complete.
