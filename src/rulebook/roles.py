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

Effective role = override(token) or seed(token) or "novice".

The ladder answers "how privileged?" as a single rank, which can't express
per-feature asks like "see the Advanced page but not the Users tab" or "edit
your own gold but not others'". So authorization is *also* expressed as
**capabilities** (see docs/rbac-capabilities.md): endpoints gate on a named
capability via `require_capability`, and a role is a bundle of capabilities
(`ROLE_CAPABILITIES`). The ladder is retained for role *ordering* (the Users-
tab picker) and the legacy `require_role`; the capability map is the authority
on what a role may *do*. Gating is a no-op when demo_mode is off (a public
deploy has no identities to authorize) — for both mechanisms it fails closed to
the public tier.
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


# ── Capabilities ───────────────────────────────────────────────────────────
#
# Named permissions a role either has or hasn't. Capability strings are STABLE
# identifiers that outlive UI labels: the Advanced surface is gated by
# `advanced.view` even while the HTTP route is still /admin/* and the page still
# reads "Admin" — that relabel is cosmetic and lands later; the capability is
# named for what it will be, so it never becomes an unmoored `admin.*` fossil.

# Main app.
CAP_ASK = "ask"
CAP_RATE = "rate"
CAP_FEEDBACK_ANNOTATE = "feedback.annotate"   # attach tags/notes to feedback
CAP_GOLD_AUTHOR = "gold.author"               # write a gold answer (POST /gold)
# Advanced (admin) surface.
CAP_ADVANCED_VIEW = "advanced.view"           # see the Advanced page shell at all
CAP_FEEDBACK_VIEW = "feedback.view"
CAP_GOLDS_VIEW = "golds.view"
CAP_GOLDS_CURATE = "golds.curate"             # toggle a gold's Incl.
CAP_GOLDS_EDIT_OWN = "golds.edit.own"         # edit a gold you authored
CAP_GOLDS_EDIT_ANY = "golds.edit.any"         # edit any gold
CAP_SOURCES_VIEW = "sources.view"
CAP_SOURCES_CURATE = "sources.curate"
CAP_INDEX_REBUILD = "index.rebuild"           # the Rebuild Index button
CAP_USERS_MANAGE = "users.manage"             # Users tab: invites + role changes
CAP_ROLES_MANAGE = "roles.manage"             # change the RBAC config itself

# The full closed set — every capability a role may be granted.
CAPABILITIES: frozenset[str] = frozenset({
    CAP_ASK, CAP_RATE, CAP_FEEDBACK_ANNOTATE, CAP_GOLD_AUTHOR,
    CAP_ADVANCED_VIEW, CAP_FEEDBACK_VIEW, CAP_GOLDS_VIEW, CAP_GOLDS_CURATE,
    CAP_GOLDS_EDIT_OWN, CAP_GOLDS_EDIT_ANY, CAP_SOURCES_VIEW, CAP_SOURCES_CURATE,
    CAP_INDEX_REBUILD, CAP_USERS_MANAGE, CAP_ROLES_MANAGE,
})

# Role → capability bundle. Built so the existing five behave EXACTLY as they
# did under the ladder — this slice changes the *mechanism* (rank → capability),
# not the *policy*. In particular user/role management stays superuser-only:
# admin deliberately does NOT get users.manage/roles.manage, matching today's
# superuser-gated /admin/invite-tokens and /admin/roles. Granting admin
# users.manage later is a one-line move into `_ADMIN` — which is the whole point
# of the capability model.
_PUBLIC = frozenset({CAP_ASK, CAP_RATE})
_EVALUATOR = _PUBLIC | {CAP_FEEDBACK_ANNOTATE, CAP_GOLD_AUTHOR}
# The full Advanced surface an admin may touch: read every tab, curate, rebuild.
# Carries golds.edit.any (edit *any* gold), which supersedes golds.edit.own — so
# admin/superuser intentionally do NOT hold edit.own; that restricted "your own
# only" form is for the curator tier (the OR-check in docs/rbac-capabilities.md
# §4 means edit.any alone already grants editing everything).
_ADVANCED_FULL = frozenset({
    CAP_ADVANCED_VIEW, CAP_FEEDBACK_VIEW, CAP_GOLDS_VIEW, CAP_GOLDS_CURATE,
    CAP_GOLDS_EDIT_ANY, CAP_SOURCES_VIEW, CAP_SOURCES_CURATE, CAP_INDEX_REBUILD,
})
_ADMIN = _EVALUATOR | _ADVANCED_FULL
_SUPERUSER = _ADMIN | {CAP_USERS_MANAGE, CAP_ROLES_MANAGE}

# New capability-defined roles (docs/rbac-capabilities.md). Every human role
# builds on _PUBLIC, so an observer can still ask questions — they gain
# read-only sight of the machinery on top. Defined here so the model + tests are
# complete, but NOT yet offered in the assignment UI (the picker still shows
# ROLE_LADDER) until the RBAC-frontend slice turns them on. Names are
# placeholders — rename freely.
_OBSERVER = _PUBLIC | {
    CAP_ADVANCED_VIEW, CAP_FEEDBACK_VIEW, CAP_GOLDS_VIEW, CAP_SOURCES_VIEW,
}
_CURATOR_LITE = _OBSERVER | {CAP_GOLDS_CURATE, CAP_INDEX_REBUILD}
_CURATOR = _CURATOR_LITE | {CAP_FEEDBACK_ANNOTATE, CAP_GOLD_AUTHOR, CAP_GOLDS_EDIT_OWN}

ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    "suspended": frozenset(),
    "novice": _PUBLIC,
    "evaluator": _EVALUATOR,
    "admin": _ADMIN,
    "superuser": _SUPERUSER,
    "observer": _OBSERVER,
    "curator-lite": _CURATOR_LITE,
    "curator": _CURATOR,
}

# What a public (demo_mode off) deploy allows anonymously — the novice tier.
PUBLIC_CAPABILITIES: frozenset[str] = ROLE_CAPABILITIES[DEFAULT_ROLE]

# Refresh window for the GCS overrides — same rationale as the token source.
DEFAULT_TTL_SECONDS = 30.0

# Cache of replayed overrides {token: role}, keyed by (bucket, object).
_overrides_cache: dict[tuple[str, str], tuple[float, dict[str, str]]] = {}


def is_valid_role(role: str) -> bool:
    # Any role with a defined capability bundle is assignable — this now
    # includes the capability-only roles (observer/…), not just the ladder.
    return role in ROLE_CAPABILITIES


def _rank(role: str) -> int:
    try:
        return ROLE_LADDER.index(role)
    except ValueError:
        # Unknown role string → treat as the safe floor, never as elevated.
        return 0


def at_least(role: str, minimum: str) -> bool:
    return _rank(role) >= _rank(minimum)


def capabilities_for(role: str) -> frozenset[str]:
    """The capability bundle for a role; empty for unknown roles (fail closed)."""
    return ROLE_CAPABILITIES.get(role, frozenset())


def has_capability(role: str, capability: str) -> bool:
    return capability in capabilities_for(role)


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


def require_capability(capability: str) -> Callable[[], None]:
    """Dependency that 403s unless the current guest's role has `capability`.

    The capability-based counterpart to `require_role`, with the same
    fail-closed public-mode rule: when demo_mode is OFF the deploy is anonymous,
    so only PUBLIC_CAPABILITIES (the novice tier — ask/rate) are allowed and
    everything else is denied. When demo_mode is ON, the guest's effective role
    must include the capability; unknown roles resolve to an empty bundle, so
    they fail closed.
    """

    def _check() -> None:
        if not settings.demo_mode:
            if capability in PUBLIC_CAPABILITIES:
                return
            raise HTTPException(
                status_code=403,
                detail=(
                    f"'{capability}' requires demo_mode with an authenticated role; "
                    "this deploy is public (demo_mode off)"
                ),
            )
        guest = get_current_guest()
        role = resolve_role(guest.token if guest else None)
        if not has_capability(role, capability):
            raise HTTPException(
                status_code=403,
                detail=f"requires capability '{capability}'; role '{role}' lacks it",
            )

    return _check
