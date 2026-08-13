#!/usr/bin/env bash
# Copyright (c) 2026 Eric Cooper.
#
# Deploy rulebook to its production Cloud Run service.
#
# The target is hardcoded so a deploy can never drift to a stale copy in
# another project (there is a leftover `rulebook` service in pitchcraft-demo
# that serves no domain — do not deploy there). The live site
# rulebook.cooper.nu is a domain mapping onto the service below.
#
# The build stamp (git SHA + monotonic commit count) is computed here and
# passed as env vars, which build_info.py prefers over a git lookup — the
# image excludes .git/, so without this the footer reads "unknown / ?".
#
# Usage:  scripts/deploy.sh          # deploy current HEAD
#         scripts/deploy.sh --dry-run
set -euo pipefail

PROJECT="rulebook-prod"
REGION="us-central1"
SERVICE="rulebook"

SHA="$(git rev-parse --short HEAD)"
NUM="$(git rev-list --count HEAD)"
test -n "$SHA" || { echo "error: empty git SHA" >&2; exit 1; }
test -n "$NUM" || { echo "error: empty build number" >&2; exit 1; }

if [ -n "$(git status --porcelain)" ]; then
    echo "warning: working tree is dirty — the stamp ($SHA) will not match what is deployed" >&2
fi

echo "Deploying $SERVICE to $PROJECT ($REGION) — build $NUM ($SHA)"

if [ "${1:-}" = "--dry-run" ]; then
    echo "gcloud run deploy $SERVICE --source . --project $PROJECT --region $REGION \\"
    echo "  --update-env-vars RULEBOOK_GIT_SHA=$SHA,RULEBOOK_BUILD_NUM=$NUM"
    exit 0
fi

exec gcloud run deploy "$SERVICE" \
    --source . \
    --project "$PROJECT" \
    --region "$REGION" \
    --update-env-vars "RULEBOOK_GIT_SHA=$SHA,RULEBOOK_BUILD_NUM=$NUM"
