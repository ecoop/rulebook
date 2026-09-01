# Deploy runbook

_Last updated: 2026-08-31_

How the hosted, gated demo is deployed.

## Current deployment

- **Deploy:** `./scripts/deploy.sh` → your dedicated Cloud Run project (the
  script reads `RULEBOOK_PROJECT` / `RULEBOOK_REGION` / `RULEBOOK_SERVICE` from
  the environment). It runs a cached kaniko build (`cloudbuild.yaml`) then
  `gcloud run deploy --image`; `--no-cache` falls back to the original
  `--source .` path. See the script header for details.
- **Project / bucket layout** and the "give the service its own project" runbook:
  [`migrate-to-dedicated-project.md`](migrate-to-dedicated-project.md).
- **Demo gating concepts** (invite auth, cost caps): [`demo-mode.md`](demo-mode.md).
- **Roles / capabilities and managing invitees:** [`roles.md`](roles.md),
  [`rbac-capabilities.md`](rbac-capabilities.md), [`users-tab.md`](users-tab.md).
