# Migrate rulebook → its own `rulebook-prod` project

_Last updated: 2026-08-11_

> **Executed 2026-08-11.** Phases 1–6 done and verified — `rulebook.cooper.nu` now serves
> from `rulebook-prod` (401 gate, Coop=superuser). **Only Phase 8 (decommission) is
> pending** — the old bits in `pitchcraft-demo` are left as rollback insurance. This
> doc doubles as the template for the same jobscout / pitchcraft moves.

rulebook was launched inside the shared **`pitchcraft-demo`** project by mistake.
This runbook relocates it to a dedicated **`rulebook-prod`** project (one project
per service). It's a **migration of a live, gated demo** — data already exists in
`gs://rulebook-state` and `rulebook.cooper.nu` is serving — so it adds a domain
cutover and a decommission that jobscout's fresh-deploy runbook doesn't.

**Owner tags:** `[Eric]` = human-only (project/billing, DNS/domain, secrets,
deletions). `[verify]` = assistant read-only gate check. `[gate]` = precondition
that must be green before proceeding.

**Constants**
```
PROJECT=rulebook-prod          REGION=us-central1        SERVICE=rulebook
BUCKET=rulebook-prod-state     DOMAIN=rulebook.cooper.nu
ORG=758999444712 (eric-org)    BILLING=01316D-67C114-9BA54F
RUNTIME_SA=rulebook-runtime@rulebook-prod.iam.gserviceaccount.com
# migrating FROM:
SRC_PROJECT=pitchcraft-demo    SRC_BUCKET=rulebook-state
```

## Two sharp edges — read before starting
1. **Domain ownership does NOT carry across projects.** `cooper.nu` is verified for
   `pitchcraft-demo`; you must re-verify it for `rulebook-prod` (Phase 2) or Cloud
   Run won't issue the managed cert for the mapping.
2. **`anthropic-api-key` and `voyage-api-key` are SHARED** with pitchcraft in
   `pitchcraft-demo`. Copy their *values* into `rulebook-prod` (Phase 4), but in the
   decommission (Phase 8) **only delete rulebook-specific things** — never those two
   shared secrets, or you break pitchcraft.

---

## `[gate]` Before any cutover
- **Project ready** — `rulebook-prod` created, billing linked, APIs on, `cooper.nu`
  re-verified (Phases 1–2).
- **New service healthy on its `*.run.app` URL** — gated 401, and your token logs in
  (Phase 5 `[verify]`), *before* the domain moves (Phase 6).

---

## Phase 0 — pick a globally-unique project ID  `[Eric]`
GCP project IDs are unique across **all** of GCP, not just your account — so generic
names (`rulebook-demo`, `rulebook-prod`, `jobscout-demo`) may already be taken by
strangers. Symptoms: `projects create` fails *"ID already in use by another project"*
and you can't see/access it (it's someone else's). Pick an ID that's actually free;
the project **display name** can still be clean. This runbook uses **`rulebook-prod`**
(created 2026-08-11 under org `eric-org`; billing linked, APIs on).

## Phase 1 — project + APIs  `[Eric]`  ✅ done for rulebook-prod
```bash
gcloud projects create rulebook-prod --organization=758999444712
gcloud billing projects link rulebook-prod --billing-account=01316D-67C114-9BA54F
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com storage.googleapis.com \
  --project=rulebook-prod
```

## Phase 2 — domain ownership in the new project  `[Eric]`
In practice (rulebook-prod, 2026-08-11) verification **carried over** — Search Console
domain verification is per-**account**, and `cooper.nu` was already verified for
`eric@cooper.nu` from the pitchcraft mapping, so the Phase 6 `create` issued the cert
with **no TXT challenge**. Only if `domain-mappings create` returns a TXT challenge do
you add that record in Plesk (or [Search Console](https://search.google.com/search-console))
and retry. The `rulebook → ghs.googlehosted.com` CNAME already exists in Plesk and
**stays** — only the mapping's project changes.

## Phase 3 — runtime SA, bucket, copy state  `[Eric]`
```bash
gcloud iam service-accounts create rulebook-runtime --project=rulebook-prod

gcloud storage buckets create gs://rulebook-prod-state \
  --project=rulebook-prod --location=us-central1 --uniform-bucket-level-access

# Copy ALL live state (index/, invite_tokens.json, logs/, roles.jsonl) old → new.
gcloud storage cp --recursive "gs://rulebook-state/*" gs://rulebook-prod-state/

# The service reads AND writes the bucket (log write-through, roles.jsonl) → objectAdmin.
gcloud storage buckets add-iam-policy-binding gs://rulebook-prod-state \
  --member="serviceAccount:rulebook-runtime@rulebook-prod.iam.gserviceaccount.com" \
  --role=roles/storage.objectAdmin
```
`[verify]` new bucket mirrors the old (`index/`, `invite_tokens.json`, `logs/`, `roles.jsonl`).

## Phase 4 — secrets  `[Eric]`
Copy the two shared keys' values across, and move the rulebook-only role seed:
```bash
for S in anthropic-api-key voyage-api-key rulebook-initial-roles; do
  gcloud secrets versions access latest --secret="$S" --project=pitchcraft-demo \
    | gcloud secrets create "$S" --project=rulebook-prod --data-file=-
  gcloud secrets add-iam-policy-binding "$S" --project=rulebook-prod \
    --member="serviceAccount:rulebook-runtime@rulebook-prod.iam.gserviceaccount.com" \
    --role=roles/secretmanager.secretAccessor
done
```

## Phase 5 — deploy the service to the new project  `[Eric]`
First, a fresh project's **compute** SA (used as the Cloud Build SA for `--source`
deploys) lacks build permissions — grant it once, or the first deploy fails with
`storage.objects.get denied on ...run-sources...`:
```bash
NUM=$(gcloud projects describe rulebook-prod --format='value(projectNumber)')
gcloud projects add-iam-policy-binding rulebook-prod \
  --member="serviceAccount:${NUM}-compute@developer.gserviceaccount.com" \
  --role=roles/cloudbuild.builds.builder
```
Then deploy from the rulebook repo root on `main`:
```bash
gcloud run deploy rulebook --project=rulebook-prod --region=us-central1 --source . \
  --allow-unauthenticated --max-instances=1 \
  --service-account=rulebook-runtime@rulebook-prod.iam.gserviceaccount.com \
  --set-env-vars=STATE_BACKEND_KIND=gcs,GCS_STATE_BUCKET=rulebook-prod-state,RULEBOOK_DEMO_MODE=true,GUARDRAILS_ENABLED=true,RULEBOOK_DATA_DIR=/tmp/rulebook/data,INDEX_PATH=/tmp/rulebook/index \
  --set-secrets=ANTHROPIC_API_KEY=anthropic-api-key:latest,VOYAGE_API_KEY=voyage-api-key:latest,RULEBOOK_INITIAL_ROLES=rulebook-initial-roles:latest
```
(First `--source` deploy may prompt to grant Cloud Build permissions — accept.)

`[verify]` on the service's **`*.run.app`** URL (not the domain yet): un-tokened → 401,
`?token=<Coop>` → 200. **Do not move the domain until this passes.**

## Phase 6 — cut the domain over  `[Eric]`  ← brief downtime
```bash
gcloud beta run domain-mappings delete --domain=rulebook.cooper.nu \
  --region=us-central1 --project=pitchcraft-demo
gcloud beta run domain-mappings create --service=rulebook --domain=rulebook.cooper.nu \
  --region=us-central1 --project=rulebook-prod
```
CNAME is unchanged (`ghs.googlehosted.com`). The managed cert re-provisions for the new
project (minutes–hours). `[verify]` `domain-mappings describe` → Ready/CertProvisioned;
then `https://rulebook.cooper.nu/` → 401, `?token=<Coop>` → 200, Users tab loads.

## Phase 7 — `[gate]` new demo fully verified live
Coop logs in on `rulebook.cooper.nu`, Users tab shows the 23, a question answers. Only
then proceed to decommission.

## Phase 8 — decommission the old rulebook bits in `pitchcraft-demo`  `[Eric]`
**Only rulebook-specific resources. Do NOT touch `anthropic-api-key` / `voyage-api-key`
(shared with pitchcraft).**
```bash
gcloud run services delete rulebook --region=us-central1 --project=pitchcraft-demo
gcloud storage rm --recursive gs://rulebook-state --project=pitchcraft-demo
gcloud beta run domain-mappings delete --domain=rulebook.cooper.nu \
  --region=us-central1 --project=pitchcraft-demo   # if not already removed in Phase 6
gcloud secrets delete rulebook-initial-roles --project=pitchcraft-demo
```

---

## Rollback
If the new deploy misbehaves before Phase 8, the old service still exists in
`pitchcraft-demo`. Re-point the domain back:
```bash
gcloud beta run domain-mappings delete --domain=rulebook.cooper.nu --region=us-central1 --project=rulebook-prod
gcloud beta run domain-mappings create --service=rulebook --domain=rulebook.cooper.nu --region=us-central1 --project=pitchcraft-demo
```
Nothing is deleted until Phase 8, so rollback is just a domain re-point.
