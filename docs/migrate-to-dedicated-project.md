<!-- Copyright (c) 2026 Eric Cooper. -->
# Give the service its own GCP project

_Last updated: 2026-08-31_

A runbook for putting the `rulebook` Cloud Run service in its **own** GCP project
(one project per service). Two flavors:

- **Fresh deploy** — a brand-new project with no prior data. Skip the state-copy
  and decommission phases; do Phases 0–2, 5–6.
- **Migration** — relocating a *live, gated* instance that already has data in a
  bucket and a domain serving traffic. Do every phase — the extra work is the
  state copy (Phase 3), the domain cutover (Phase 6), and decommissioning the old
  project (Phase 8).

**Placeholders** — set these to your own values before running anything:
```
PROJECT=<PROJECT>              REGION=us-central1        SERVICE=rulebook
BUCKET=<STATE_BUCKET>          DOMAIN=rulebook.cooper.nu
ORG=<ORG_ID>                   BILLING=<BILLING_ACCOUNT>
RUNTIME_SA=<RUNTIME_SA>        # e.g. rulebook-runtime@<PROJECT>.iam.gserviceaccount.com
# migration only — the project/bucket you're moving away from:
SRC_PROJECT=<SRC_PROJECT>      SRC_BUCKET=<SRC_BUCKET>
```

**Owner tags:** `[Eric]` = human-only (project/billing, DNS/domain, secrets,
deletions). `[verify]` = read-only gate check. `[gate]` = precondition that must
be green before proceeding.

## Two sharp edges — read before starting (migration)
1. **Domain ownership does NOT carry across projects.** A domain verified for
   `<SRC_PROJECT>` must be re-verified for `<PROJECT>` (Phase 2) or Cloud Run
   won't issue the managed cert for the mapping. (In practice, Search Console
   verification is per-*account*, so if the same account owns both it often
   carries over with no TXT challenge — but don't count on it.)
2. **Shared secrets stay shared.** If `anthropic-api-key` / `voyage-api-key` are
   shared with another service in `<SRC_PROJECT>`, copy their *values* into
   `<PROJECT>` (Phase 4) but in the decommission (Phase 8) **only delete
   service-specific resources** — never a shared secret, or you break the other
   service.

---

## `[gate]` Before any cutover (migration)
- **Project ready** — `<PROJECT>` created, billing linked, APIs on, domain
  re-verified (Phases 1–2).
- **New service healthy on its `*.run.app` URL** — gated 401, and a valid token
  logs in (Phase 5 `[verify]`), *before* the domain moves (Phase 6).

---

## Phase 0 — pick a globally-unique project ID  `[Eric]`
GCP project IDs are unique across **all** of GCP, not just your account — so
generic names may already be taken by strangers. Symptom: `projects create` fails
*"ID already in use by another project"* and you can't see it (it's someone
else's). Pick an ID that's actually free; the project **display name** can still
be clean.

## Phase 1 — project + APIs  `[Eric]`
```bash
gcloud projects create <PROJECT> --organization=<ORG_ID>
gcloud billing projects link <PROJECT> --billing-account=<BILLING_ACCOUNT>
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com storage.googleapis.com \
  --project=<PROJECT>
```

## Phase 2 — domain ownership in the new project  `[Eric]`
If `domain-mappings create` (Phase 6) returns a TXT challenge, add that record at
your DNS host (or [Search Console](https://search.google.com/search-console)) and
retry. A `<DOMAIN> → ghs.googlehosted.com` CNAME must exist and **stays** — only
the mapping's project changes.

## Phase 3 — runtime SA, bucket, copy state  `[Eric]`  *(migration)*
```bash
gcloud iam service-accounts create rulebook-runtime --project=<PROJECT>

gcloud storage buckets create gs://<STATE_BUCKET> \
  --project=<PROJECT> --location=us-central1 --uniform-bucket-level-access

# Copy ALL live state (index/, invite_tokens.json, logs/, roles.jsonl) old → new.
gcloud storage cp --recursive "gs://<SRC_BUCKET>/*" gs://<STATE_BUCKET>/

# The service reads AND writes the bucket (log write-through, roles.jsonl) → objectAdmin.
gcloud storage buckets add-iam-policy-binding gs://<STATE_BUCKET> \
  --member="serviceAccount:<RUNTIME_SA>" \
  --role=roles/storage.objectAdmin
```
`[verify]` new bucket mirrors the old (`index/`, `invite_tokens.json`, `logs/`, `roles.jsonl`).

## Phase 4 — secrets  `[Eric]`
Copy the API keys' values across, and (migration) move the role seed:
```bash
for S in anthropic-api-key voyage-api-key rulebook-initial-roles; do
  gcloud secrets versions access latest --secret="$S" --project=<SRC_PROJECT> \
    | gcloud secrets create "$S" --project=<PROJECT> --data-file=-
  gcloud secrets add-iam-policy-binding "$S" --project=<PROJECT> \
    --member="serviceAccount:<RUNTIME_SA>" \
    --role=roles/secretmanager.secretAccessor
done
```

## Phase 5 — deploy the service to the new project  `[Eric]`
First, a fresh project's **compute** SA (used as the Cloud Build SA for `--source`
deploys) lacks build permissions — grant it once, or the first deploy fails with
`storage.objects.get denied on ...run-sources...`:
```bash
NUM=$(gcloud projects describe <PROJECT> --format='value(projectNumber)')
gcloud projects add-iam-policy-binding <PROJECT> \
  --member="serviceAccount:${NUM}-compute@developer.gserviceaccount.com" \
  --role=roles/cloudbuild.builds.builder
```
Then deploy from the repo root on `main`:
```bash
gcloud run deploy rulebook --project=<PROJECT> --region=us-central1 --source . \
  --allow-unauthenticated --max-instances=1 \
  --service-account=<RUNTIME_SA> \
  --set-env-vars=STATE_BACKEND_KIND=gcs,GCS_STATE_BUCKET=<STATE_BUCKET>,RULEBOOK_DEMO_MODE=true,GUARDRAILS_ENABLED=true,RULEBOOK_DATA_DIR=/tmp/rulebook/data,INDEX_PATH=/tmp/rulebook/index \
  --set-secrets=ANTHROPIC_API_KEY=anthropic-api-key:latest,VOYAGE_API_KEY=voyage-api-key:latest,RULEBOOK_INITIAL_ROLES=rulebook-initial-roles:latest
```
(First `--source` deploy may prompt to grant Cloud Build permissions — accept.)

`[verify]` on the service's **`*.run.app`** URL (not the domain yet): un-tokened →
401, `?token=<valid>` → 200. **Do not move the domain until this passes.**

## Phase 6 — cut the domain over  `[Eric]`  ← brief downtime *(migration)*
```bash
gcloud beta run domain-mappings delete --domain=<DOMAIN> \
  --region=us-central1 --project=<SRC_PROJECT>
gcloud beta run domain-mappings create --service=rulebook --domain=<DOMAIN> \
  --region=us-central1 --project=<PROJECT>
```
The CNAME is unchanged (`ghs.googlehosted.com`). The managed cert re-provisions for
the new project (minutes–hours). `[verify]` `domain-mappings describe` →
Ready/CertProvisioned; then `https://<DOMAIN>/` → 401, `?token=<valid>` → 200.

## Phase 7 — `[gate]` new demo fully verified live  *(migration)*
A real user logs in on `<DOMAIN>`, the Users tab loads, a question answers. Only
then proceed to decommission.

## Phase 8 — decommission the old bits in `<SRC_PROJECT>`  `[Eric]`  *(migration)*
**Only service-specific resources. Do NOT touch secrets shared with another
service in `<SRC_PROJECT>`.**
```bash
gcloud run services delete rulebook --region=us-central1 --project=<SRC_PROJECT>
gcloud storage rm --recursive gs://<SRC_BUCKET> --project=<SRC_PROJECT>
gcloud beta run domain-mappings delete --domain=<DOMAIN> \
  --region=us-central1 --project=<SRC_PROJECT>   # if not already removed in Phase 6
gcloud secrets delete rulebook-initial-roles --project=<SRC_PROJECT>
```

---

## Rollback (migration)
If the new deploy misbehaves before Phase 8, the old service still exists in
`<SRC_PROJECT>`. Re-point the domain back:
```bash
gcloud beta run domain-mappings delete --domain=<DOMAIN> --region=us-central1 --project=<PROJECT>
gcloud beta run domain-mappings create --service=rulebook --domain=<DOMAIN> --region=us-central1 --project=<SRC_PROJECT>
```
Nothing is deleted until Phase 8, so rollback is just a domain re-point.
