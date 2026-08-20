# Copyright (c) 2026 Eric Cooper.
"""The domain registry (#113 part 2) — content config for each domain.

A THIRD config layer, distinct from the other two:
  - app/deploy config  → env vars (config.py Settings): operator-set, same for all.
  - user state/privileges → append-only logs (roles.jsonl, allowed_domains.jsonl).
  - **content config**  → THIS registry: which domains exist and their metadata.

The registry is *current state* (the present set of domains and how each is
described), not an event log — so it's a whole-object ``domains.json`` snapshot
(same shape/TTL as invite_tokens.json), overwritten on edit, NOT a `.jsonl` log.

It is **authoritative for identity + enabled**: a domain shows in the product
iff it's in the index AND enabled here. Everything else (display name, source
URLs for point-and-download, citation-numbering hint) is metadata. A domain in
the index but ABSENT from the registry falls back to a sensible default —
enabled, name = title-cased slug — so nothing disappears without an explicit
``enabled: false``.

Resolution mirrors the other stores: seed (``initial_domains``) overlaid by the
GCS object, TTL-cached.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from .config import settings

log = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 30.0

# bucket -> (expiry_monotonic, {slug: raw-entry-dict})
_registry_cache: dict[str, tuple[float, dict[str, dict]]] = {}


@dataclass(frozen=True)
class DomainInfo:
    slug: str
    display_name: str
    # Point-and-download URLs for the (often copyrighted) source docs — the home
    # of the "here's where to get each domain's rules" pointers.
    sources: list[str] = field(default_factory=list)
    # Citation-format hint for this domain (e.g. "§ {rule_id}"); None = the
    # default "[{slug} {rule_id}]". Stored now; wired into generation later.
    numbering: str | None = None
    enabled: bool = True


def _default_name(slug: str) -> str:
    return slug.replace("_", " ").replace("-", " ").title()


def _entry_to_info(slug: str, entry: Mapping[str, object]) -> DomainInfo:
    return DomainInfo(
        slug=slug,
        display_name=str(entry.get("display_name") or "") or _default_name(slug),
        sources=[str(u) for u in (entry.get("sources") or [])],
        numbering=(str(entry["numbering"]) if entry.get("numbering") else None),
        enabled=bool(entry.get("enabled", True)),
    )


# ── Resolution ────────────────────────────────────────────────────────────


def domain_info(slug: str, declared: Mapping[str, dict] | None = None) -> DomainInfo:
    """Registry entry for a slug, or a sensible default if it's not declared."""
    if declared is None:
        declared = _declared_registry()
    entry = declared.get(slug)
    return _entry_to_info(slug, entry) if entry is not None else DomainInfo(
        slug=slug, display_name=_default_name(slug)
    )


def resolve_registry(index_domains: Iterable[str]) -> dict[str, DomainInfo]:
    """{slug: DomainInfo} for each domain in the index (declared or defaulted)."""
    declared = _declared_registry()
    return {slug: domain_info(slug, declared) for slug in index_domains}


def visible_domains(index_domains: Iterable[str]) -> list[str]:
    """Index domains that are enabled in the registry, in the given order.

    This is the authoritative "which domains does the product show" list —
    before the per-user allowlist (#112) narrows it further.
    """
    declared = _declared_registry()
    return [s for s in index_domains if domain_info(s, declared).enabled]


def display_labels(index_domains: Iterable[str]) -> dict[str, str]:
    """{slug: display_name} for the given domains — powers the picker labels."""
    declared = _declared_registry()
    return {s: domain_info(s, declared).display_name for s in index_domains}


def declared_domains() -> list[str]:
    """Slugs the registry declares (seed ⊕ GCS object) — for the grant menu."""
    return sorted(_declared_registry())


def _declared_registry() -> dict[str, dict]:
    """Seed ⊕ GCS object, TTL-cached; {slug: raw-entry-dict}. Seed unless gcs."""
    seed: dict[str, dict] = dict(settings.initial_domains)
    if settings.state_backend_kind != "gcs" or not settings.gcs_state_bucket:
        return seed
    bucket, obj = settings.gcs_state_bucket, settings.domains_object
    now = time.monotonic()
    cached = _registry_cache.get(bucket)
    if cached is not None and now < cached[0]:
        return cached[1]
    obj_entries = _read_registry(bucket, obj)
    if obj_entries is None:  # read failed — reuse last-good, else seed only
        merged = cached[1] if cached is not None else seed
    else:
        merged = {**seed, **obj_entries}  # GCS object wins over the env seed
    _registry_cache[bucket] = (now + DEFAULT_TTL_SECONDS, merged)
    return merged


def _read_registry(bucket: str, obj: str) -> dict[str, dict] | None:
    try:
        return read_registry_object(bucket, obj)
    except Exception:  # noqa: BLE001 — a bad bucket read must not break serving
        log.exception("registry: failed reading gs://%s/%s; reusing last-good", bucket, obj)
        return None


# ── GCS storage (whole-object json snapshot) ───────────────────────────────


def read_registry_object(bucket: str, obj: str) -> dict[str, dict]:
    """The {slug: entry} map from the domains.json object; {} if absent."""
    from google.cloud import storage

    blob = storage.Client().bucket(bucket).blob(obj)
    if not blob.exists():
        return {}
    return json.loads(blob.download_as_text())


def write_registry_object(bucket: str, obj: str, mapping: Mapping[str, dict]) -> None:
    """Overwrite the domains.json object (whole-object snapshot, like tokens)."""
    from google.cloud import storage

    blob = storage.Client().bucket(bucket).blob(obj)
    blob.upload_from_string(
        json.dumps(dict(mapping), indent=2, sort_keys=True),
        content_type="application/json",
    )
    _registry_cache.pop(bucket, None)  # reflect the write immediately
