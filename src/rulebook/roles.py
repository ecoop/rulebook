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

Effective role = override(token) or seed(token) or default (level1). Roles are
numbered levels, level0 (suspended) … level8 (superuser); see ROLE_LEVELS.

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

import hashlib
import json
import logging
import time
from collections.abc import Callable, Iterable, Mapping

from fastapi import HTTPException
from guest_auth import get_current_guest

from .config import settings

log = logging.getLogger(__name__)

# Roles are numbered LEVELS, 0–8 (docs/rbac-capabilities.md §4): the number makes
# the ordering self-evident (level5 > level4, no lore required). Level 0 is a
# suspended account (no access); 1–8 are the rungs. Each level also carries a
# color and a one-line description for a UI badge — see ROLE_LEVELS below.
ROLE_LADDER: tuple[str, ...] = (
    "level0", "level1", "level2", "level3", "level4",
    "level5", "level6", "level7", "level8",
)
DEFAULT_ROLE = "level1"   # a new / unseeded token is a beginner
RESET_SENTINEL = "reset"  # a roles.jsonl row role that clears an override


# ── Capabilities ───────────────────────────────────────────────────────────
#
# Named permissions a role either has or hasn't (docs/rbac-capabilities.md).
# Capability strings are STABLE identifiers, independent of UI labels and routes:
# the Advanced surface is gated by `advanced.view`, served under /advanced/*.
#
# The eight rungs (§4 of the doc) form a monotonic chain, so each bundle below is
# the previous one plus more. Some capabilities are DEFINED here but their
# behaviour lands in a later slice — noted inline; the vocabulary and the role
# assignments are correct now, the features (self/all filtering, clone, audit,
# attribution) follow.

# Main page.
CAP_ASK = "ask"
CAP_RATE = "rate"                             # numeric 1–5 rating
CAP_FEEDBACK_TAG = "feedback.tag"             # attach issue tags to a rating
CAP_FEEDBACK_COMMENT = "feedback.comment"     # attach a free-text comment (≤400)
CAP_GOLD_AUTHOR = "gold.author"               # suggest a gold answer (POST /gold)
CAP_PASSAGES_VIEW = "passages.view"           # Retrieved-passages panel (frontend gate)
# Your-activity surface (the personal, self-scoped page — a floor for everyone).
CAP_ACTIVITY_VIEW = "activity.view"           # open the "Your activity" page shell
# Advanced surface (the operator extras that grow on top of Your activity).
CAP_ADVANCED_VIEW = "advanced.view"           # + the retrieval machinery (passages, sources)
CAP_FEEDBACK_VIEW = "feedback.view"           # Feedback tab — your own rows
CAP_FEEDBACK_VIEW_ALL = "feedback.view.all"   # …everyone's rows  (self/all slice)
CAP_GOLDS_VIEW = "golds.view"                 # Golds tab — your own rows
CAP_GOLDS_VIEW_ALL = "golds.view.all"         # …everyone's rows  (self/all slice)
CAP_QUESTIONS_VIEW_ALL = "questions.view.all" # Questions tab — everyone's, with author
CAP_GOLDS_EDIT_OWN = "golds.edit.own"         # edit a gold you authored
CAP_GOLDS_CLONE = "golds.clone"               # clone another's gold → yours  (clone slice)
CAP_GOLDS_CURATE = "golds.curate"             # toggle a gold's Incl.
CAP_SOURCES_VIEW = "sources.view"             # Sources tab (the corpus)
CAP_SOURCES_CURATE = "sources.curate"         # toggle a source's inclusion
CAP_INDEX_REBUILD = "index.rebuild"           # the Rebuild index button
CAP_ATTRIBUTION_VIEW = "attribution.view"     # the Audit tab (actor of shared-state changes);
#                                               row authors ride with the *.view.all tier (L5)
CAP_USERS_VIEW = "users.view"                 # Users tab — see rows
CAP_USERS_CHANGE_ROLE = "users.change_role"   # change a user's role
CAP_USERS_ADD = "users.add"                   # add an invitee
CAP_USERS_REMOVE = "users.remove"             # hard-delete an invite
CAP_USERS_RENAME = "users.rename"             # rename a user's label
CAP_ROLES_MANAGE = "roles.manage"             # edit the RBAC config itself (no endpoint yet)

# The full closed set — every capability a role may be granted.
CAPABILITIES: frozenset[str] = frozenset({
    CAP_ASK, CAP_RATE, CAP_FEEDBACK_TAG, CAP_FEEDBACK_COMMENT, CAP_GOLD_AUTHOR,
    CAP_ACTIVITY_VIEW,
    CAP_PASSAGES_VIEW, CAP_ADVANCED_VIEW, CAP_FEEDBACK_VIEW, CAP_FEEDBACK_VIEW_ALL,
    CAP_GOLDS_VIEW, CAP_GOLDS_VIEW_ALL, CAP_QUESTIONS_VIEW_ALL,
    CAP_GOLDS_EDIT_OWN, CAP_GOLDS_CLONE,
    CAP_GOLDS_CURATE, CAP_SOURCES_VIEW, CAP_SOURCES_CURATE, CAP_INDEX_REBUILD,
    CAP_ATTRIBUTION_VIEW, CAP_USERS_VIEW, CAP_USERS_CHANGE_ROLE, CAP_USERS_ADD,
    CAP_USERS_REMOVE, CAP_USERS_RENAME, CAP_ROLES_MANAGE,
})

# The eight rungs, cumulative (each = the previous ∪ its additions). See §4.
# The self-scoped "revisit your own work" caps live LOW on the ladder — everyone
# gets a personal "Your activity" page that grows as they climb (issue #74/#51).
_R1 = frozenset({                                                # casual player + your activity
    CAP_ASK, CAP_RATE, CAP_FEEDBACK_TAG,
    CAP_ACTIVITY_VIEW, CAP_FEEDBACK_VIEW,                        # revisit your own questions/ratings
})
_R2 = _R1 | {CAP_FEEDBACK_COMMENT}                               # + explain a rating
_R3 = _R2 | {                                                    # + suggest & revisit your own golds
    CAP_GOLD_AUTHOR, CAP_GOLDS_VIEW, CAP_GOLDS_EDIT_OWN,
}
_R4 = _R3 | {                                                    # + the retrieval machinery (self)
    CAP_ADVANCED_VIEW, CAP_PASSAGES_VIEW, CAP_SOURCES_VIEW,
}
_R5 = _R4 | {                                                    # read all (with authors), write own
    CAP_FEEDBACK_VIEW_ALL, CAP_GOLDS_VIEW_ALL, CAP_QUESTIONS_VIEW_ALL,
}
_R6 = _R5 | {                                                    # operator
    CAP_GOLDS_CURATE, CAP_GOLDS_CLONE, CAP_SOURCES_CURATE,
    CAP_INDEX_REBUILD, CAP_ATTRIBUTION_VIEW,
}
_R7 = _R6 | {CAP_USERS_VIEW, CAP_USERS_CHANGE_ROLE, CAP_USERS_ADD}  # admin
_R8 = _R7 | {CAP_USERS_REMOVE, CAP_USERS_RENAME, CAP_ROLES_MANAGE}  # superuser

# Role → capability bundle, keyed by level (§4). Policy encoded here: level7
# (admin) manages users — view, change role, add invitees; level8 (superuser)
# holds the destructive ops (remove/rename) plus the future RBAC-config editor
# (roles.manage).
ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    "level0": frozenset(),  # suspended
    "level1": _R1,          # casual player
    "level2": _R2,          # + explain a rating
    "level3": _R3,          # + suggest answers
    "level4": _R4,          # behind the curtain (self)
    "level5": _R5,          # read all, write own
    "level6": _R6,          # operator
    "level7": _R7,          # admin
    "level8": _R8,          # superuser
}

# Presentation for each level — color (a judo-belt palette; red breaks the ramp
# for the top rank) and a short description, for a colorful UI badge. Hardcoded
# here as the single source of truth; expose via the API rather than duplicating
# in the frontend.
ROLE_LEVELS: dict[str, dict[str, object]] = {
    "level0": {"level": 0, "name": "Suspended", "color": "#9AA0A6", "description": "No access"},
    "level1": {"level": 1, "name": "Beginner", "color": "#E8E8E8", "description": "Ask and rate answers"},
    "level2": {"level": 2, "name": "Annotator", "color": "#E5B80B", "description": "Comment on answers"},
    "level3": {"level": 3, "name": "Contributor", "color": "#E07A20", "description": "Suggest and revisit your own golds"},
    "level4": {"level": 4, "name": "Builder", "color": "#3A8C3A", "description": "See the passages and sources behind answers"},
    "level5": {"level": 5, "name": "Reviewer", "color": "#2C64B4", "description": "Review everyone's work"},
    "level6": {"level": 6, "name": "Director", "color": "#7A4A2B", "description": "Curate & clone golds, rebuild index, audit"},
    "level7": {"level": 7, "name": "Admin", "color": "#1A1A1A", "description": "Users tab; change roles"},
    "level8": {"level": 8, "name": "Superuser", "color": "#C4272E", "description": "Remove/rename users; RBAC config"},
}


def level_number(role: str) -> int:
    """Numeric level for a role (0 for suspended / unknown)."""
    meta = ROLE_LEVELS.get(role)
    return int(meta["level"]) if meta else 0

# What a public (demo_mode off) deploy allows anonymously — the novice tier.
PUBLIC_CAPABILITIES: frozenset[str] = ROLE_CAPABILITIES[DEFAULT_ROLE]

# Refresh window for the GCS overrides — same rationale as the token source.
DEFAULT_TTL_SECONDS = 30.0

# Cache of replayed overrides {token: role}, keyed by (bucket, object).
_overrides_cache: dict[tuple[str, str], tuple[float, dict[str, str]]] = {}


def is_valid_role(role: str) -> bool:
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


def capability_fingerprint(caps: Iterable[str]) -> str:
    """Short content-address of a capability SET (docs/rbac-data-driven-roles.md).

    Order-independent by construction (sort before hashing), so the same set of
    capabilities always yields the same 8-hex fingerprint regardless of how it
    was assembled. A fingerprint, NOT an identity: it changes whenever the set
    changes, so it's for dedup / "did this role's powers change?" / audit — not
    the assignment key.
    """
    canonical = ",".join(sorted(set(caps)))
    return hashlib.sha256(canonical.encode()).hexdigest()[:8]


def role_fingerprint(role: str) -> str:
    """Fingerprint of a role's CURRENT capability bundle (empty set → its own hash)."""
    return capability_fingerprint(capabilities_for(role))


# ── Resolution ────────────────────────────────────────────────────────────


def resolve_role(token: str | None) -> str:
    """Effective level for a token: override ▸ seed ▸ default (level1)."""
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
            # Public: allow only what the default (level1) may do; deny higher.
            if at_least(DEFAULT_ROLE, minimum):
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
