# Copyright (c) 2026 Eric Cooper.
"""Per-user ruleset access — a token→rulesets allowlist (#112).

A **data-scope** axis, deliberately separate from the role/capability ladder
(docs/design/rulesets-and-access.md, Area 3): the role says *how privileged*,
this says *which rulesets you may see*. It never grants a capability — it only
restricts, ANDed after the capability check.

Resolution mirrors roles.py exactly:

    seed       RULEBOOK_INITIAL_ALLOWED_SPORTS, {token: [rulesets]}. Baseline.
    overrides  an append-only `allowed_sports.jsonl` object in the state
               bucket, written by the Users-tab API. Latest row per token
               wins; a `reset` row falls back to the seed/default.

Effective allowlist = override(token) ▸ seed(token) ▸ default. The default
(``settings.default_allowed_sports``) is a CONCRETE set — today's two sports —
NOT "all": a newly-added ruleset is in no one's allowlist until explicitly
granted (#112's chosen policy). A `*` grant row means *all rulesets, including
any added later*; it resolves to ``None`` = unrestricted. A token with no
identity (demo_mode off / public deploy) is also unrestricted — scoping is a
no-op there, matching how role gating no-ops without identities.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterable, Mapping

from .config import settings

log = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 30.0
ALL_SENTINEL = "*"        # a grant row meaning "every ruleset, now and future"
RESET_SENTINEL = "reset"  # a row that clears an override back to seed/default

# (bucket, obj) -> (expiry_monotonic, {token: [rulesets] | "*"})
_grants_cache: dict[tuple[str, str], tuple[float, dict[str, list[str] | str]]] = {}


# ── Resolution ────────────────────────────────────────────────────────────


def resolve_allowed_sports(token: str | None) -> list[str] | None:
    """Effective ruleset allowlist for a token, or ``None`` = unrestricted.

    override ▸ seed ▸ default. ``None`` means "all rulesets" — returned for a
    ``*`` grant and for a missing identity (``token is None``). A concrete list
    is returned otherwise; the default is ``settings.default_allowed_sports``.
    """
    if token is None:
        return None
    grants = _effective_grants()
    if token in grants:
        grant = grants[token]
    elif token in settings.initial_allowed_sports:
        grant = settings.initial_allowed_sports[token]
    else:
        grant = list(settings.default_allowed_sports)
    if grant == ALL_SENTINEL:
        return None
    return list(grant)


def _effective_grants() -> dict[str, list[str] | str]:
    """TTL-cached {token: allowlist} from the GCS log; {} unless gcs."""
    if settings.state_backend_kind != "gcs" or not settings.gcs_state_bucket:
        return {}
    bucket, obj = settings.gcs_state_bucket, settings.allowed_sports_object
    key = (bucket, obj)
    now = time.monotonic()
    cached = _grants_cache.get(key)
    if cached is not None and now < cached[0]:
        return cached[1]
    grants = _read_grants(bucket, obj)
    if grants is None:  # read failed — reuse last-good, else empty
        grants = cached[1] if cached is not None else {}
    _grants_cache[key] = (now + DEFAULT_TTL_SECONDS, grants)
    return grants


def _read_grants(bucket: str, obj: str) -> dict[str, list[str] | str] | None:
    try:
        return grants_from_rows(read_allowed_sports_rows(bucket, obj))
    except Exception:  # noqa: BLE001 — authz must survive a bad bucket read
        log.exception("allowed_sports: failed reading gs://%s/%s; reusing last-good", bucket, obj)
        return None


def grants_from_rows(rows: Iterable[Mapping[str, object]]) -> dict[str, list[str] | str]:
    """Replay append-only rows to {token: allowlist}; latest wins, reset clears."""
    out: dict[str, list[str] | str] = {}
    for row in rows:
        token = str(row.get("token", ""))
        sports = row.get("sports")
        if not token:
            continue
        if sports == RESET_SENTINEL:
            out.pop(token, None)
        elif sports == ALL_SENTINEL:
            out[token] = ALL_SENTINEL
        elif isinstance(sports, list):
            out[token] = [str(s) for s in sports]
        # else: malformed row — skip, don't corrupt the map
    return out


# ── Enforcement helper ─────────────────────────────────────────────────────


def constrain_sports(
    requested: list[str] | None,
    allowed: list[str] | None,
) -> list[str] | None:
    """Intersect a cross-ruleset selection with the caller's allowlist.

    Returns the concrete list to retrieve against, or ``None`` = "all" (only
    when unrestricted and nothing specific was asked for — the one path that
    may legitimately hit the global search).

    - ``allowed is None`` (unrestricted): pass ``requested`` through unchanged
      (``None``/empty stays ``None`` = all).
    - empty ``requested`` for a scoped caller: their full allowlist (never the
      global all — that would be the leak footgun).
    - otherwise: ``requested ∩ allowed``, preserving requested order.

    Raises ``PermissionError`` if a specific request has no overlap at all.
    """
    if allowed is None:
        return list(requested) if requested else None
    if not requested:
        return list(allowed)
    eff = [s for s in requested if s in allowed]
    if not eff:
        raise PermissionError("none of the requested rulesets are permitted")
    return eff


# ── GCS storage (append-only jsonl object) ─────────────────────────────────


def read_allowed_sports_rows(bucket: str, obj: str) -> list[dict]:
    """All rows from the allowed_sports.jsonl object; [] if absent."""
    from google.cloud import storage

    blob = storage.Client().bucket(bucket).blob(obj)
    if not blob.exists():
        return []
    text = blob.download_as_text()
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def append_allowed_sports_row(bucket: str, obj: str, row: Mapping[str, object]) -> None:
    """Append one row to the allowed_sports.jsonl object (read-modify-write).

    Full rewrite per change — fine at this volume, and keeps the object a
    plain append-only log for audit, exactly like roles.jsonl.
    """
    from google.cloud import storage

    blob = storage.Client().bucket(bucket).blob(obj)
    existing = blob.download_as_text() if blob.exists() else ""
    line = json.dumps(dict(row), sort_keys=True)
    blob.upload_from_string(
        (existing + line + "\n") if existing else (line + "\n"),
        content_type="application/x-ndjson",
    )
    _grants_cache.pop((bucket, obj), None)  # reflect the write immediately
