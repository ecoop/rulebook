# Demo mode on Cloud Run

_Last updated: 2026-08-10_

Design doc — not yet implemented. How to run an **invite-only public demo** of Rulebook on Cloud Run: minting per-guest tokens, keeping them out of git and the image, and injecting them at deploy.

## What already exists

Invite-gated demo mode ships today via [`guest-auth`](https://github.com/ecoop/guest-auth) ([README](../README.md#invite-gated-demo-mode-optional), [config.py](../src/rulebook/config.py)):

- `RULEBOOK_DEMO_MODE=true` turns the gate on (off by default → no auth).
- `RULEBOOK_INVITE_TOKENS` is a JSON `{token: name}` map read from an **env var**. Guests visit `?token=…` → httpOnly cookie → clean-URL redirect. The name is used for logging, the Demo widget, and per-guest cost attribution.

Because tokens come from an env var, **do not bake a token file into the image** (`COPY . /app` would leak secrets into image layers and force a rebuild per guest-list change). Generate locally → gitignored file → inject at deploy.

## Two independent axes — don't conflate them

- **Who can get in (authN)** — the invite-token allowlist `{token: name}` below. *How it reaches the container* is Option A/B/C.
- **What a signed-in user can do (authZ)** — their **role** (novice → superuser), managed live via `roles.jsonl` per [roles.md](roles.md).

These are orthogonal. **Option A fully supports live promote/demote/suspend** — role changes are a `POST /admin/roles` write, never a redeploy. Under A the *only* things needing a redeploy are edits to the raw allowlist itself: adding a new person, or **renaming a token's label** (e.g. repurposing an unused invite from one person to another). Revocation dodges even that via the `suspended` role. Making allowlist edits redeploy-free is Option C ([#20](https://github.com/ecoop/rulebook/issues/20)), independent of RBAC.

## Prerequisite: minimal RBAC (audience is untrusted)

Today **any valid token grants full access** — including `/admin`, `/gold`, and everyone's `/feedback` ([roles.md](roles.md) is design-only). Cost caps (Track A) bound *spend*, but not data integrity or privacy. For an outside audience, land [roles.md](roles.md) steps 1–2 first:

- `require_role` dependency; demo tokens default to `novice`.
- Gate `/admin*` at `admin`, `/gold` at `evaluator`. Non-permitted UI hidden.

This is the blocking item — everything below assumes it (or an accepted risk sign-off).

## Token minting

`scripts/mint_invite_tokens.py`:

- Input: gitignored `secrets/demo_guests.txt` (one name per line) or CLI args.
- Per name: `tok_` + `secrets.token_hex(16)`. **Merge, don't regenerate** — keep existing tokens for known names so shared links keep working.
- Outputs (gitignored, under `secrets/`):
  - `invite_tokens.json` — the `{token: name}` map.
  - `invite_links.md` — `name → https://<host>/?token=…` for distribution.
- Add `secrets/` to both `.gitignore` and `.dockerignore`.

## Injection: Secret Manager → env var (Option A)

Best design for Cloud Run: no code change (config already reads the env var), secrets never touch the image or git, IAM-controlled, versioned rotation.

```bash
gcloud secrets create rulebook-invite-tokens --data-file=secrets/invite_tokens.json
# (later updates: gcloud secrets versions add rulebook-invite-tokens --data-file=...)

gcloud run deploy rulebook \
  --set-secrets=RULEBOOK_INVITE_TOKENS=rulebook-invite-tokens:latest \
  --set-env-vars=RULEBOOK_DEMO_MODE=true \
  --max-instances=1
```

**Later — Option C ([#20](https://github.com/ecoop/rulebook/issues/20)):** move the allowlist to a mounted file or the GCS state bucket so allowlist edits — adding a person, or renaming a token's label — become redeploy-free too. This is *not* a prerequisite for RBAC and A does not block it; it's natural to fold onto the same GCS live-config path `roles.jsonl` uses. Not now.

## Cloud Run must-dos

- **State backend = GCS.** The image ships no index (`data/` is dockerignored); each instance starts fresh. Set `state_backend_kind=gcs` + `gcs_state_bucket` (Track B) or the demo can't answer, and feedback/usage won't persist.
- **`--max-instances=1`.** The cost counter is per-instance in-memory; multiple instances under-count caps.
- **HTTPS** — required for `Secure` cookies; Cloud Run provides it.
- **Token in first-request logs** — `?token=` hits request logs once before the redirect. Low risk for demo tokens.

## Revocation

Today: drop the entry from the secret (new version) + redeploy — cookies aren't signed, so the allowlist is re-checked every request. Once RBAC's `roles.jsonl` lands, the `suspended` role gives redeploy-free revocation.
