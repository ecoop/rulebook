# Copyright (c) 2026 Eric Cooper.
#
# Rulebook — production container image.
#
# Multi-stage build:
#   1. web-builder   builds web/dist/ with Node + Vite
#   2. py-builder    installs Python deps into a venv (pip + pyproject.toml)
#   3. runtime       slim image with venv + app code + built web assets
#
# Designed for platforms that inject $PORT (Cloud Run, Fly.io, Render).
# Defaults to 8000 — matches local dev — when $PORT is unset.
#
# Modeled on pitchcraft's Dockerfile; kept in lockstep so improvements
# on one side port easily to the other.

# ─── 1. Web builder: build the React SPA ──────────────────────────────────────
FROM node:22-alpine AS web-builder

WORKDIR /web
# Install deps first for better layer caching when only source changes.
COPY web/package.json web/package-lock.json* ./
RUN npm ci --no-audit --no-fund

# Build the production bundle into /web/dist/.
COPY web/ ./
RUN npm run build


# ─── 2. Python deps builder: pip install into an isolated venv ────────────────
FROM python:3.13-slim AS py-builder

# No build toolchain: every runtime dependency ships a manylinux wheel
# (numpy, pydantic-core, anthropic, google-cloud-storage, …), so pip never
# compiles. Installing build-essential added ~150MB of download + apt work to
# every image build for nothing. If a future dep needs to compile, add exactly
# what it needs back here (and prefer a wheel).

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Create a venv we can copy whole into the runtime image — keeps the
# runtime layer free of build-essential and pip's working state.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install by project spec so pip resolves llm-cost-governor, guest-auth,
# jsonl-log, etc. from pyproject.toml — same source of truth uv uses.
# README is only referenced by [project].readme; copy it so pip can
# resolve the metadata without ferrying the whole repo yet.
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --upgrade pip && pip install .


# ─── 3. Runtime: slim image, non-root, app + venv + web bundle ────────────────
FROM python:3.13-slim AS runtime

# Build-time identity. Pass via `--build-arg GIT_SHA=... BUILD_NUM=...` so
# the startup banner shows which commit built this image (otherwise the
# banner reads "unknown / ?" because .git/ is excluded via .dockerignore).
# build_info.py reads the RULEBOOK_-prefixed env vars and prefers them
# over a git lookup.
ARG GIT_SHA=no-git
ARG BUILD_NUM=?

# Runtime env. PYTHONDONTWRITEBYTECODE keeps the image clean of *.pyc;
# PYTHONUNBUFFERED ensures logs reach the platform's log collector promptly.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8000 \
    RULEBOOK_GIT_SHA=$GIT_SHA \
    RULEBOOK_BUILD_NUM=$BUILD_NUM

# Non-root runtime user. Cloud Run rejects root processes; matches every
# other reasonable platform's default.
RUN groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --home /app --shell /sbin/nologin app

WORKDIR /app

# Copy venv from py-builder; copy built React bundle from web-builder.
COPY --from=py-builder /opt/venv /opt/venv
COPY --from=web-builder /web/dist /app/web/dist

# Application source. .dockerignore filters out caches, secrets, local
# runtime data, and node_modules; the rules/ directory rides along
# because it's source content the index build reads.
COPY --chown=app:app . /app

# Drop privileges before the runtime starts.
USER app

# Document the port — platforms that respect EXPOSE will pick this up;
# Cloud Run overrides via $PORT regardless.
EXPOSE 8000

# main.py reads $PORT and hands off to uvicorn.
CMD ["python", "main.py"]
