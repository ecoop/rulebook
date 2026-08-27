# Deploy runbook — superseded

_Last updated: 2026-08-27_

> **Historical / superseded.** This file described gating the *original*
> `pitchcraft-demo` deployment (state bucket `rulebook-state`) — both of which
> have since been **decommissioned** (see
> [`migrate-to-rulebook-prod.md`](migrate-to-rulebook-prod.md), Phase 8). The
> stale step-by-step commands were removed to avoid misleading readers; this is
> now just a pointer to the current setup.

## Current deployment

- **Deploy:** `./scripts/deploy.sh` → the dedicated **`rulebook-prod`** Cloud Run
  project. It runs a cached kaniko build (`cloudbuild.yaml`) then
  `gcloud run deploy --image`; `--no-cache` falls back to the original
  `--source .` path. See the script header for details.
- **Project / bucket layout** and the `pitchcraft-demo` → `rulebook-prod`
  migration history: [`migrate-to-rulebook-prod.md`](migrate-to-rulebook-prod.md).
- **Demo gating concepts** (invite auth, cost caps): [`demo-mode.md`](demo-mode.md).
- **Roles / capabilities and managing invitees:** [`roles.md`](roles.md),
  [`rbac-capabilities.md`](rbac-capabilities.md), [`users-tab.md`](users-tab.md).
