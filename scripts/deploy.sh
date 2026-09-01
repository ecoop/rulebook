#!/usr/bin/env bash
# Copyright (c) 2026 Eric Cooper.
#
# Deploy rulebook to its production Cloud Run service.
#
# The target project/region/service come from env vars (RULEBOOK_PROJECT is
# required; REGION and SERVICE default below), so this script carries no
# baked-in infrastructure ids. The live site rulebook.cooper.nu is a domain
# mapping onto the service.
#
# The build stamp (git SHA + monotonic commit count) is computed here and
# passed as env vars, which build_info.py prefers over a git lookup — the
# image excludes .git/, so without this the footer reads "unknown / ?".
#
# By default this uses a CACHED build (#181): `gcloud builds submit` runs
# cloudbuild.yaml (kaniko with layer caching) and then `gcloud run deploy
# --image` rolls it out. A deploy that changes only app code skips npm ci /
# pip install, cutting the build time roughly in half. If the cached path ever
# misbehaves (e.g. a Cloud Build SA permission gap on the cache repo), fall
# back to the original uncached `--source .` build:
#
# Usage:  scripts/deploy.sh              # cached build + deploy (default)
#         scripts/deploy.sh --no-cache   # original uncached `--source .` path
#         scripts/deploy.sh --dry-run    # print the commands, don't run them
set -euo pipefail

PROJECT="${RULEBOOK_PROJECT:?set RULEBOOK_PROJECT to your GCP project id (e.g. export RULEBOOK_PROJECT=my-project)}"
REGION="${RULEBOOK_REGION:-us-central1}"
SERVICE="${RULEBOOK_SERVICE:-rulebook}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/cloud-run-source-deploy/${SERVICE}"

MODE="cached"
DRY_RUN=""
for arg in "$@"; do
    case "$arg" in
        --no-cache) MODE="source" ;;
        --dry-run) DRY_RUN="1" ;;
        *) echo "error: unknown argument '$arg'" >&2; exit 2 ;;
    esac
done

SHA="$(git rev-parse --short HEAD)"
NUM="$(git rev-list --count HEAD)"
test -n "$SHA" || { echo "error: empty git SHA" >&2; exit 1; }
test -n "$NUM" || { echo "error: empty build number" >&2; exit 1; }

# Warn only on uncommitted *tracked* changes — those would make the stamp ($SHA)
# misrepresent the deployed code. Untracked files are expected here: the
# copyrighted rules/ source docs intentionally ride along via the build (they
# stay out of git), and they don't affect the code stamp.
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    echo "warning: uncommitted tracked changes — the stamp ($SHA) will not match the deployed code" >&2
fi

echo "Deploying $SERVICE to $PROJECT ($REGION) — build $NUM ($SHA) [$MODE]"

run() {
    if [ -n "$DRY_RUN" ]; then
        printf '  '; printf '%q ' "$@"; printf '\n'
    else
        "$@"
    fi
}

if [ "$MODE" = "source" ]; then
    # Fallback: original one-shot uncached build+deploy.
    run gcloud run deploy "$SERVICE" \
        --source . \
        --project "$PROJECT" \
        --region "$REGION" \
        --update-env-vars "RULEBOOK_GIT_SHA=$SHA,RULEBOOK_BUILD_NUM=$NUM"
    exit 0
fi

# Cached path (#181): kaniko build+push with layer caching, then deploy the
# built image. --update-env-vars refreshes the build stamp (overriding any
# stale service-level value) and leaves all other env/secrets on the service
# untouched.
run gcloud builds submit \
    --project "$PROJECT" \
    --region "$REGION" \
    --config cloudbuild.yaml \
    --substitutions "_IMAGE=${IMAGE},_SHA=${SHA},_NUM=${NUM}"

run gcloud run deploy "$SERVICE" \
    --image "${IMAGE}:${SHA}" \
    --project "$PROJECT" \
    --region "$REGION" \
    --update-env-vars "RULEBOOK_GIT_SHA=$SHA,RULEBOOK_BUILD_NUM=$NUM"
