# Copyright (c) 2026 Eric Cooper.
"""Populate the local vector index from GCS at startup.

In a hosted container the index does NOT ship in the image (``data/`` is
dockerignored) and ``repo_root`` resolves to an unwritable site-packages
ancestor. Instead the index lives in a GCS bucket and is pulled once, at
process start, into ``settings.resolved_index_path`` — a writable path such
as ``/tmp/rulebook/index`` — before any retrieval runs.

Local dev never touches this: ``state_backend_kind`` stays ``"local"`` and
the index sits under the repo where ``scripts/build_index.py`` wrote it.

The pull is best-effort. A GCS failure logs and returns without raising, so
the process still boots and serves ``/meta`` and the web bundle; only
``/ask`` degrades until the index is present. That keeps a transient bucket
hiccup from turning into a crash-loop.
"""

from __future__ import annotations

import logging

from .config import settings
from .store import CHUNKS_FILE, MANIFEST_FILE, VECTORS_FILE

log = logging.getLogger(__name__)

# The three files that make up an index directory (see store.py). Kept in
# sync with that module's constants so a rename there flows through here.
_INDEX_FILES = (VECTORS_FILE, CHUNKS_FILE, MANIFEST_FILE)

# Object-name prefix inside the bucket. The bucket doubles as the cost
# counter's StateBackend home, so the index gets its own namespace.
_GCS_PREFIX = "index/"


def sync_index_from_gcs() -> bool:
    """Download every per-domain index tree from GCS into ``resolved_index_path``.

    Per-domain layout (#128): each domain lives under ``index/<domain>/`` in the
    bucket and is pulled into ``resolved_index_path/<domain>/``. No-op (returns
    ``False``) unless ``state_backend_kind == "gcs"`` and a bucket is configured.
    Returns ``True`` when at least one domain's index was pulled.
    """
    if settings.state_backend_kind != "gcs" or not settings.gcs_state_bucket:
        return False

    bucket_name = settings.gcs_state_bucket
    dest_root = settings.resolved_index_path

    try:
        # Lazy import: only hosted (gcs) deploys carry/need the SDK path.
        from google.cloud import storage

        dest_root.mkdir(parents=True, exist_ok=True)
        client = storage.Client()
        bucket = client.bucket(bucket_name)

        # Enumerate the domain "subdirs" under index/ via a delimited listing.
        blobs = client.list_blobs(bucket_name, prefix=_GCS_PREFIX, delimiter="/")
        for _ in blobs:  # must consume the iterator to populate .prefixes
            pass
        domains = sorted(p[len(_GCS_PREFIX):].rstrip("/") for p in blobs.prefixes)

        pulled_domains = 0
        for domain in domains:
            dest = dest_root / domain
            dest.mkdir(parents=True, exist_ok=True)
            got = 0
            for name in _INDEX_FILES:
                blob = bucket.blob(f"{_GCS_PREFIX}{domain}/{name}")
                if not blob.exists():
                    continue
                blob.download_to_filename(str(dest / name))
                got += 1
            if got:
                pulled_domains += 1

        log.info(
            "index sync: pulled %d domain(s) %s from gs://%s/%s into %s",
            pulled_domains,
            domains,
            bucket_name,
            _GCS_PREFIX,
            dest_root,
        )
        return pulled_domains > 0
    except Exception:  # noqa: BLE001 — boot must survive a bad bucket pull
        log.exception(
            "index sync: failed pulling index from gs://%s/%s; "
            "/ask will error until the index is present",
            bucket_name,
            _GCS_PREFIX,
        )
        return False


def publish_index_to_gcs(domain: str | None = None) -> bool:
    """Upload built per-domain index tree(s) from ``resolved_index_path`` to GCS.

    Per-domain (#128): each domain's ``resolved_index_path/<domain>/`` is pushed
    to ``index/<domain>/`` in the bucket. Pass ``domain`` to publish just one (a
    targeted rebuild); omit it to publish every built domain. The mirror of
    :func:`sync_index_from_gcs`; without it a hosted rebuild lives only in the
    instance's ephemeral ``/tmp`` and is lost on the next restart.

    No-op (returns ``False``) unless ``state_backend_kind == "gcs"`` and a
    bucket is set. Best-effort: a failed push logs and returns ``False``.
    """
    if settings.state_backend_kind != "gcs" or not settings.gcs_state_bucket:
        return False

    from .store import list_domains

    bucket_name = settings.gcs_state_bucket
    root = settings.resolved_index_path
    domains = [domain] if domain else list_domains(root)

    try:
        from google.cloud import storage

        client = storage.Client()
        bucket = client.bucket(bucket_name)

        pushed_domains = 0
        for dom in domains:
            src = root / dom
            got = 0
            for name in _INDEX_FILES:
                path = src / name
                if not path.exists():
                    log.warning("index publish: %s missing — skipping", path)
                    continue
                bucket.blob(f"{_GCS_PREFIX}{dom}/{name}").upload_from_filename(str(path))
                got += 1
            if got:
                pushed_domains += 1

        log.info(
            "index publish: pushed %d domain(s) %s to gs://%s/%s",
            pushed_domains,
            domains,
            bucket_name,
            _GCS_PREFIX,
        )
        return pushed_domains > 0
    except Exception:  # noqa: BLE001 — a bad push shouldn't crash the rebuild
        log.exception(
            "index publish: failed pushing index to gs://%s/%s",
            bucket_name,
            _GCS_PREFIX,
        )
        return False
