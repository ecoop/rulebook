# Copyright (c) 2026 Eric Cooper.
"""Sync the source rulebooks (rules/<domain>/…) between the local dir and GCS.

The rule PDFs used to ride along inside the container image, so every deploy's
build context and image grew with the corpus (#170). Instead they live in the
GCS state bucket under ``rules/`` and are pulled into a writable local dir when
needed — the same treatment the vector index gets (see ``index_sync``).

``/ask`` never needs them: it reads the prebuilt index. Only the source
listing / diagnostics and an *in-container* rebuild read the PDFs, so this is
best-effort and lazy:

    * ``sync_rules_from_gcs()`` — download ``rules/**`` from the bucket into
      ``settings.rules_dir`` (a writable path in hosted mode). Called at boot
      (so the source views populate) and before a rebuild (freshness).
    * ``publish_rules_to_gcs()`` — upload the local ``rules/`` tree to the
      bucket. Seeds the bucket the container syncs from; run once, and again
      whenever the corpus changes.

No-op off GCS — local dev reads the repo's ``rules/`` directly. The pull is
best-effort (a bucket error logs and returns 0 so boot/rebuild survive); the
push propagates errors so an operator running the publish script sees failures.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .config import settings

log = logging.getLogger(__name__)

_GCS_PREFIX = "rules/"
# The source docs the index build reads; skip anything else (dotfiles, etc.).
_SUFFIXES = (".pdf", ".md", ".txt")


def _enabled() -> bool:
    return settings.state_backend_kind == "gcs" and bool(settings.gcs_state_bucket)


def sync_rules_from_gcs() -> int:
    """Download ``rules/**`` from GCS into ``settings.rules_dir``.

    Returns the number of files pulled. No-op (0) off GCS. Best-effort: a
    bucket error logs and returns 0 so boot and rebuild survive a bad pull (the
    source views just render empty until the next successful sync).
    """
    if not _enabled():
        return 0
    bucket_name = settings.gcs_state_bucket
    dest_root = settings.rules_dir
    try:
        # Lazy import: only hosted (gcs) deploys carry/need the SDK path.
        from google.cloud import storage

        dest_root.mkdir(parents=True, exist_ok=True)
        client = storage.Client()
        pulled = 0
        for blob in client.list_blobs(bucket_name, prefix=_GCS_PREFIX):
            rel = blob.name[len(_GCS_PREFIX):]
            if not rel or blob.name.endswith("/"):
                continue  # skip the prefix "directory" placeholder
            dest = dest_root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            blob.download_to_filename(str(dest))
            pulled += 1
        log.info(
            "rules sync: pulled %d file(s) from gs://%s/%s into %s",
            pulled, bucket_name, _GCS_PREFIX, dest_root,
        )
        return pulled
    except Exception:  # noqa: BLE001 — boot/rebuild must survive a bad pull
        log.exception(
            "rules sync: failed pulling rules from gs://%s/%s; source views and "
            "rebuild will see an empty corpus until the next sync",
            bucket_name, _GCS_PREFIX,
        )
        return 0


def publish_rules_to_gcs(source_dir: Path | None = None) -> int:
    """Upload the local ``rules/`` tree to GCS under the ``rules/`` prefix.

    Seeds the bucket the container syncs from. Returns the number of files
    uploaded. No-op (0) off GCS. Unlike the pull, errors PROPAGATE — this is
    operator-run (see ``scripts/publish_rules.py``), and a silent partial
    upload is worse than a loud failure.
    """
    if not _enabled():
        return 0
    bucket_name = settings.gcs_state_bucket
    root = source_dir or settings.rules_dir
    if not root.is_dir():
        log.warning("rules publish: %s is not a directory — nothing to upload", root)
        return 0

    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    pushed = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _SUFFIXES:
            continue
        rel = path.relative_to(root).as_posix()
        bucket.blob(f"{_GCS_PREFIX}{rel}").upload_from_filename(str(path))
        pushed += 1
    log.info(
        "rules publish: uploaded %d file(s) from %s to gs://%s/%s",
        pushed, root, bucket_name, _GCS_PREFIX,
    )
    return pushed
