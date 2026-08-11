# Deploy runbook — flip rulebook.cooper.nu to a gated demo

_Last updated: 2026-08-11_

Operator runbook for turning the **already-deployed** rulebook service into an invite-only, cost-capped demo. Conceptual background is in [demo-mode.md](demo-mode.md); roles are in [roles.md](roles.md). Every command here is **outward/human-executed** — run them yourself; don't hand them to an agent.

## Verified current state (read-only, `<SRC_PROJECT>` / `us-central1`)

The heavy infra is already in place — only a config flip remains.

| Thing | State |
|---|---|
| Service | `rulebook` → `https://rulebook.cooper.nu`, deploys via `gcloud run deploy --source .` |
| Runtime SA | `<PROJECT_NUMBER>-compute@developer.gserviceaccount.com` (already has bucket + API-key-secret access) |
| Bucket `<SRC_BUCKET>` | exists; `index/{vectors.npy,chunks.jsonl,manifest.json}` uploaded; `invite_tokens.json` present but empty (`{}`); no `roles.jsonl` yet |
| Env already set | `STATE_BACKEND_KIND=gcs`, `GCS_STATE_BUCKET=<SRC_BUCKET>`, `RULEBOOK_DATA_DIR=/tmp/rulebook/data`, `INDEX_PATH=/tmp/rulebook/index` |
| Secrets already wired | `ANTHROPIC_API_KEY`→`anthropic-api-key`, `VOYAGE_API_KEY`→`voyage-api-key` |
| **Missing for the demo** | `RULEBOOK_DEMO_MODE`, `GUARDRAILS_ENABLED`, `RULEBOOK_INITIAL_ROLES` (no superuser seeded); `--max-instances` is `20`, want `1` |

Re-verify before acting (state drifts):
```bash
gcloud run services describe rulebook --project <SRC_PROJECT> --region us-central1 \
  --format='yaml(spec.template.spec.containers[0].env, spec.template.spec.serviceAccountName)'
gcloud storage ls -r gs://<SRC_BUCKET>/
```

## The flip

### 1 · Mint a superuser token and add it to the allowlist
Needs ADC (`gcloud auth application-default login`). The allowlist is the live GCS object — this write takes effect within ~30s, no redeploy.
```bash
SU="tok_$(uuidgen | tr -d - | tr '[:upper:]' '[:lower:]')"; echo "SUPERUSER TOKEN: $SU"
STATE_BACKEND_KIND=gcs GCS_STATE_BUCKET=<SRC_BUCKET> uv run python -m scripts.invite_tokens add "Eric" --token "$SU"
```

### 2 · Seed that token as `superuser` (secret) and grant the runtime SA
Role seeds are credentials → Secret Manager, never an env literal.
```bash
printf '{"%s":"superuser"}' "$SU" | gcloud secrets create rulebook-initial-roles --project <SRC_PROJECT> --data-file=-
gcloud secrets add-iam-policy-binding rulebook-initial-roles --project <SRC_PROJECT> \
  --member="serviceAccount:<PROJECT_NUMBER>-compute@developer.gserviceaccount.com" \
  --role=roles/secretmanager.secretAccessor
```

### 3 · Redeploy from current `main` with the gated config
Run from the repo root on `main`. `--source .` rebuilds so the image carries the merged web work (Users tab, role gating, restyle). `--update-*` **merges** with the existing env/secrets — it does not clobber `STATE_BACKEND_KIND` etc.
```bash
gcloud run deploy rulebook --project <SRC_PROJECT> --region us-central1 --source . --max-instances=1 \
  --update-env-vars=RULEBOOK_DEMO_MODE=true,GUARDRAILS_ENABLED=true \
  --update-secrets=RULEBOOK_INITIAL_ROLES=rulebook-initial-roles:latest
```
Cost caps default to `$0.50/hr · $2/day · $10/wk · $1/guest-wk`; tighten with `CAP_HOURLY_USD` / `CAP_DAILY_USD` / `CAP_WEEKLY_USD` / `CAP_PER_TOKEN_USD` in `--update-env-vars` if desired.

### 4 · Verify (re-checked predicates)
```bash
curl -s -o /dev/null -w '%{http_code}\n' https://rulebook.cooper.nu/               # expect 401 now (invite-only)
curl -s -o /dev/null -w '%{http_code}\n' "https://rulebook.cooper.nu/?token=$SU"   # expect 200 / redirect
```
Then open `https://rulebook.cooper.nu/?token=$SU` in a browser → you're signed in as **superuser** → `#/admin` shows the **Users** tab and the restyled tables.

## Add invitees (live, no redeploy)
From the **Users** tab, or the CLI:
```bash
STATE_BACKEND_KIND=gcs GCS_STATE_BUCKET=<SRC_BUCKET> uv run python -m scripts.invite_tokens add "Alice"
```
Share `https://rulebook.cooper.nu/?token=<tok>` with each person. Roles default to `novice` (rate only); promote to `evaluator` (tags/notes/gold) or `admin` from the Users tab.

## Manage / revoke (live)
- Promote / demote / **suspend** (reversible, keeps audit): Users tab, or `POST /admin/roles`.
- Hard-remove an invite: Users tab "Remove", or `uv run python -m scripts.invite_tokens rm tok_…`.
- Renaming a token's label: fine when unused; for a *used* token, mint fresh and `suspended` the old one (see [#20](https://github.com/ecoop/rulebook/issues/20)).

## Rollback (un-gate)
```bash
gcloud run services update rulebook --project <SRC_PROJECT> --region us-central1 \
  --update-env-vars=RULEBOOK_DEMO_MODE=false
```

## Notes
- `--max-instances=1` keeps the in-memory cost counter coherent; more instances under-count caps.
- Updating the index later: rebuild locally (`uv run python scripts/build_index.py`) and re-upload `gs://<SRC_BUCKET>/index/`; the next cold start pulls it.
