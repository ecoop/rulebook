# Copyright (c) 2026 Eric Cooper.
"""Invite-token allowlist sources for guest-auth.

`guest-auth` answers "who is this token?" by looking it up in a Mapping it
reads from ``config.invite_tokens`` *per request* (see the middleware's
``allowlist = self._config.invite_tokens``). This module supplies that
Mapping from one of two backends:

    env  — a static seed dict, the historical RULEBOOK_INVITE_TOKENS. The
           only source in local dev.
    gcs  — a JSON object ``{token: label}`` in the state bucket, merged
           OVER the seed and refreshed on a short TTL. Lets a hosted deploy
           add or remove users by rewriting one object — no redeploy.

The seam here (`get_invite_tokens` + the read/write helpers) is kept
deliberately app-agnostic — no rulebook config import, primitives in and
out — so it can be lifted into `guest-auth` later and shared with
pitchcraft, per the "build in one app, prove it, then extract" pattern the
shared libs (jsonl-log, llm-cost-governor) already followed.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from collections.abc import Mapping

log = logging.getLogger(__name__)


def mint_token() -> str:
    """A fresh opaque, URL-safe invite token, `tok_`-prefixed for readability."""
    return "tok_" + secrets.token_urlsafe(16)

# Default refresh window for the GCS object. Short enough that a
# just-added user can sign in within seconds across every instance,
# long enough that steady request traffic doesn't hammer the bucket.
DEFAULT_TTL_SECONDS = 30.0

# Module-level cache of the GCS *overrides* only (never the seed, which is
# always re-applied fresh), keyed by (bucket, object). Kept here rather than
# on the Settings instance so pydantic stays a plain data object and tests
# constructing throwaway Settings don't fight an instance cache.
_overrides_cache: dict[tuple[str, str], tuple[float, dict[str, str]]] = {}


def get_invite_tokens(
    *,
    kind: str,
    bucket: str | None,
    object_name: str,
    seed: Mapping[str, str],
    ttl_seconds: float = DEFAULT_TTL_SECONDS,
) -> dict[str, str]:
    """Return the effective ``{token: label}`` allowlist.

    Local/non-gcs deploys get the seed verbatim. GCS deploys get
    ``{**seed, **gcs_object}`` with the object read at most once per
    ``ttl_seconds``. Best-effort: a GCS failure reuses the last good
    overrides (or just the seed on cold start), so auth never hard-fails
    on a transient bucket error.
    """
    merged_seed = dict(seed)
    if kind != "gcs" or not bucket:
        return merged_seed

    key = (bucket, object_name)
    now = time.monotonic()
    cached = _overrides_cache.get(key)
    if cached is not None and now < cached[0]:
        return {**merged_seed, **cached[1]}

    overrides = _read_overrides(bucket, object_name)
    if overrides is None:  # read failed — reuse last-good, else empty
        overrides = cached[1] if cached is not None else {}
    _overrides_cache[key] = (now + ttl_seconds, overrides)
    return {**merged_seed, **overrides}


def _read_overrides(bucket: str, object_name: str) -> dict[str, str] | None:
    """Fetch and parse the GCS allowlist object. None signals failure."""
    try:
        return read_tokens_object(bucket, object_name)
    except Exception:  # noqa: BLE001 — auth must survive a bad bucket read
        log.exception(
            "token source: failed reading gs://%s/%s; reusing last-good/seed",
            bucket,
            object_name,
        )
        return None


def read_tokens_object(bucket: str, object_name: str) -> dict[str, str]:
    """Read ``{token: label}`` from GCS. ``{}`` if the object is absent.

    Raises on transport/parse errors — callers that must not fail (the
    per-request path) go through ``_read_overrides``; management callers
    (the CLI) want the raise.
    """
    from google.cloud import storage

    client = storage.Client()
    blob = client.bucket(bucket).blob(object_name)
    if not blob.exists():
        return {}
    data = json.loads(blob.download_as_text())
    if not isinstance(data, dict):
        raise ValueError(f"gs://{bucket}/{object_name} is not a JSON object")
    return {str(k): str(v) for k, v in data.items()}


def write_tokens_object(bucket: str, object_name: str, mapping: Mapping[str, str]) -> None:
    """Overwrite the GCS allowlist object with ``mapping`` (pretty JSON)."""
    from google.cloud import storage

    client = storage.Client()
    blob = client.bucket(bucket).blob(object_name)
    blob.upload_from_string(
        json.dumps(dict(mapping), indent=2, sort_keys=True),
        content_type="application/json",
    )
    # Drop the read cache so an add/remove in this process takes effect
    # immediately (other instances still refresh within their TTL).
    _overrides_cache.pop((bucket, object_name), None)
