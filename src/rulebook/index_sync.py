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
    """Download the index objects from GCS into ``resolved_index_path``.

    No-op (returns ``False``) unless ``state_backend_kind == "gcs"`` and a
    bucket is configured — i.e. local dev and any non-GCS deploy skip it.
    Returns ``True`` when at least one index file was pulled.
    """
    if settings.state_backend_kind != "gcs" or not settings.gcs_state_bucket:
        return False

    bucket_name = settings.gcs_state_bucket
    dest = settings.resolved_index_path

    try:
        # Lazy import: only hosted (gcs) deploys carry/need the SDK path.
        from google.cloud import storage

        dest.mkdir(parents=True, exist_ok=True)
        client = storage.Client()
        bucket = client.bucket(bucket_name)

        pulled = 0
        for name in _INDEX_FILES:
            blob = bucket.blob(f"{_GCS_PREFIX}{name}")
            if not blob.exists():
                log.warning(
                    "index sync: gs://%s/%s%s missing — skipping",
                    bucket_name,
                    _GCS_PREFIX,
                    name,
                )
                continue
            blob.download_to_filename(str(dest / name))
            pulled += 1

        log.info(
            "index sync: pulled %d/%d files from gs://%s/%s into %s",
            pulled,
            len(_INDEX_FILES),
            bucket_name,
            _GCS_PREFIX,
            dest,
        )
        return pulled > 0
    except Exception:  # noqa: BLE001 — boot must survive a bad bucket pull
        log.exception(
            "index sync: failed pulling index from gs://%s/%s; "
            "/ask will error until the index is present",
            bucket_name,
            _GCS_PREFIX,
        )
        return False


def publish_index_to_gcs() -> bool:
    """Upload the freshly-built index from ``resolved_index_path`` to GCS.

    The mirror of :func:`sync_index_from_gcs`. Without it, a rebuild (the
    ``/advanced/rebuild-index`` button) writes only the instance's ephemeral
    ``/tmp`` copy and is lost on the next restart, which re-pulls the *old*
    objects — so a hosted rebuild never sticks. Call this after
    ``build_index`` writes the store so the rebuild is durable and every
    instance converges on it at next boot.

    No-op (returns ``False``) unless ``state_backend_kind == "gcs"`` and a
    bucket is set. Best-effort: a failed push logs and returns ``False``
    rather than failing the build.
    """
    if settings.state_backend_kind != "gcs" or not settings.gcs_state_bucket:
        return False

    bucket_name = settings.gcs_state_bucket
    src = settings.resolved_index_path

    try:
        from google.cloud import storage

        client = storage.Client()
        bucket = client.bucket(bucket_name)

        pushed = 0
        for name in _INDEX_FILES:
            path = src / name
            if not path.exists():
                log.warning("index publish: %s missing — skipping", path)
                continue
            bucket.blob(f"{_GCS_PREFIX}{name}").upload_from_filename(str(path))
            pushed += 1

        log.info(
            "index publish: pushed %d/%d files from %s to gs://%s/%s",
            pushed,
            len(_INDEX_FILES),
            src,
            bucket_name,
            _GCS_PREFIX,
        )
        return pushed > 0
    except Exception:  # noqa: BLE001 — a bad push shouldn't crash the rebuild
        log.exception(
            "index publish: failed pushing index to gs://%s/%s",
            bucket_name,
            _GCS_PREFIX,
        )
        return False
