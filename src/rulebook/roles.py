# Copyright (c) 2026 Eric Cooper.
"""Role-based authorization layered on guest-auth (see docs/roles.md).

guest-auth answers *who is this token?* (identity). This module answers
*what may they do?* — a small monotonic ladder resolved from two sources:

    seed       RULEBOOK_INITIAL_ROLES, {token: role}. Baseline; redeploy to
               change. Must seed at least one `superuser` (bootstrap).
    overrides  an append-only `roles.jsonl` object in the state bucket,
               written by the superuser API. Latest row per token wins; a
               `reset` row falls back to the seed. Persists across restarts,
               changes live (no redeploy) — the durability stopgap from
               docs/roles.md ("direct-to-GCS for roles").

Effective role = override(token) or seed(token) or "novice". The ladder is
monotonic so `require_role(min)` is one comparison. Gating is a no-op when
demo_mode is off (a public deploy has no identities to authorize).
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterable, Mapping

from fastapi import HTTPException
from guest_auth import get_current_guest

from .config import settings

log = logging.getLogger(__name__)

# Monotonic ladder, lowest → highest. Index is the rank used for comparison.
# `suspended` is a floor (rank 0) that fails every `require_role(novice+)`.
ROLE_LADDER: tuple[str, ...] = ("suspended", "novice", "evaluator", "admin", "superuser")
DEFAULT_ROLE = "novice"
RESET_SENTINEL = "reset"  # a roles.jsonl row role that clears an override

# Refresh window for the GCS overrides — same rationale as the token source.
DEFAULT_TTL_SECONDS = 30.0

# Cache of replayed overrides {token: role}, keyed by (bucket, object).
_overrides_cache: dict[tuple[str, str], tuple[float, dict[str, str]]] = {}


def is_valid_role(role: str) -> bool:
    return role in ROLE_LADDER


def _rank(role: str) -> int:
    try:
        return ROLE_LADDER.index(role)
    except ValueError:
        # Unknown role string → treat as the safe floor, never as elevated.
        return 0


def at_least(role: str, minimum: str) -> bool:
    return _rank(role) >= _rank(minimum)


# ── Resolution ────────────────────────────────────────────────────────────


def resolve_role(token: str | None) -> str:
    """Effective role for a token: override ▸ seed ▸ novice."""
    if token is None:
        return DEFAULT_ROLE
    overrides = _effective_overrides()
    if token in overrides:
        return overrides[token]
    return settings.initial_roles.get(token, DEFAULT_ROLE)


def _effective_overrides() -> dict[str, str]:
    """TTL-cached {token: role} from the GCS roles.jsonl; {} unless gcs."""
    if settings.state_backend_kind != "gcs" or not settings.gcs_state_bucket:
        return {}
    bucket, obj = settings.gcs_state_bucket, settings.roles_object
    key = (bucket, obj)
    now = time.monotonic()
    cached = _overrides_cache.get(key)
    if cached is not None and now < cached[0]:
        return cached[1]
    overrides = _read_overrides(bucket, obj)
    if overrides is None:  # read failed — reuse last-good, else empty
        overrides = cached[1] if cached is not None else {}
    _overrides_cache[key] = (now + DEFAULT_TTL_SECONDS, overrides)
    return overrides


def _read_overrides(bucket: str, obj: str) -> dict[str, str] | None:
    try:
        return overrides_from_rows(read_role_rows(bucket, obj))
    except Exception:  # noqa: BLE001 — authz must survive a bad bucket read
        log.exception("roles: failed reading gs://%s/%s; reusing last-good", bucket, obj)
        return None


def overrides_from_rows(rows: Iterable[Mapping[str, object]]) -> dict[str, str]:
    """Replay append-only rows to {token: role}; latest wins, reset clears."""
    out: dict[str, str] = {}
    for row in rows:
        token = str(row.get("token", ""))
        role = str(row.get("role", ""))
        if not token:
            continue
        if role == RESET_SENTINEL:
            out.pop(token, None)
        elif is_valid_role(role):
            out[token] = role
    return out


# ── GCS storage (append-only jsonl object) ─────────────────────────────────


def read_role_rows(bucket: str, obj: str) -> list[dict]:
    """All rows from the roles.jsonl object; [] if absent."""
    from google.cloud import storage

    blob = storage.Client().bucket(bucket).blob(obj)
    if not blob.exists():
        return []
    text = blob.download_as_text()
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def append_role_row(bucket: str, obj: str, row: Mapping[str, object]) -> None:
    """Append one row to the roles.jsonl object (read-modify-write).

    Full rewrite per change — fine at this volume (dozens of entries,
    changes weekly at most, per docs/roles.md) and keeps the object a
    plain append-only log for audit.
    """
    from google.cloud import storage

    blob = storage.Client().bucket(bucket).blob(obj)
    existing = blob.download_as_text() if blob.exists() else ""
    line = json.dumps(dict(row), sort_keys=True)
    blob.upload_from_string(
        (existing + line + "\n") if existing else (line + "\n"),
        content_type="application/x-ndjson",
    )
    _overrides_cache.pop((bucket, obj), None)  # reflect the write immediately


# ── FastAPI dependency ─────────────────────────────────────────────────────


def require_role(minimum: str) -> Callable[[], None]:
    """Dependency that 403s unless the current guest is at least `minimum`.

    When demo_mode is OFF the deploy is public and has no identities to
    authorize. Rather than open everything (which would expose the admin
    and role-write surface anonymously), it FAILS CLOSED for privileged
    tiers: only the public tier (`novice` and below — i.e. /ask, /feedback,
    /me) is allowed; evaluator/admin/superuser are denied. So a public
    deploy keeps working for asking, but /gold and /admin/* stay locked
    until demo_mode is on and a real role is present.
    """

    def _check() -> None:
        if not settings.demo_mode:
            # Public: allow only what novice may do; deny anything higher.
            if at_least("novice", minimum):
                return
            raise HTTPException(
                status_code=403,
                detail=(
                    f"'{minimum}' requires demo_mode with an authenticated role; "
                    "this deploy is public (demo_mode off)"
                ),
            )
        guest = get_current_guest()
        role = resolve_role(guest.token if guest else None)
        if not at_least(role, minimum):
            raise HTTPException(
                status_code=403,
                detail=f"requires role '{minimum}'; you are '{role}'",
            )

    return _check
