# Copyright (c) 2026 Eric Cooper.
"""Persist the append-only JSONL logs to the GCS state bucket.

On a hosted (``state_backend_kind == "gcs"``) deploy the log dir lives on
ephemeral ``/tmp`` (``RULEBOOK_DATA_DIR``), so feedback / gold / qa rows are
lost on every cold start. This module makes them durable the same way
``index_sync`` handles the index:

    * ``sync_logs_from_gcs()`` — at startup, download each log object into the
      local log dir, so reads (which still go through ``jsonl_log`` against
      local files) see prior state.
    * ``persist_log(filename)`` — after each append, upload the whole file
      back to GCS (write-through).

Whole-file write-through self-heals: a transient upload failure is corrected
by the next successful append, since every upload pushes the complete file.
Best-effort throughout — a bucket error never breaks a request or boot. A
no-op when the backend isn't GCS, so local dev is unchanged. Single-writer
assumption (max-instances=1) matches ``jsonl_log``'s in-process append lock.
"""

from __future__ import annotations

import logging

from .config import settings

log = logging.getLogger(__name__)

# The append-only logs written by interaction_log. Object name mirrors the
# local filename under the `logs/` prefix in the state bucket.
LOG_FILES: tuple[str, ...] = (
    "qa_log.jsonl",
    "feedback.jsonl",
    "gold.jsonl",
    "gold_curation.jsonl",
    "source_curation.jsonl",
    "index_builds.jsonl",
)
_GCS_PREFIX = "logs/"


def _enabled() -> bool:
    return settings.state_backend_kind == "gcs" and bool(settings.gcs_state_bucket)


def _bucket():
    from google.cloud import storage

    return storage.Client().bucket(settings.gcs_state_bucket)


def sync_logs_from_gcs() -> None:
    """Download the JSONL logs from GCS into the local log dir. Best-effort.

    No-op unless the GCS backend is configured. Mirrors
    ``index_sync.sync_index_from_gcs`` — boot must survive a bad bucket.
    """
    if not _enabled():
        return
    log_dir = settings.data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    try:
        bucket = _bucket()
        pulled = 0
        for name in LOG_FILES:
            blob = bucket.blob(f"{_GCS_PREFIX}{name}")
            if blob.exists():
                blob.download_to_filename(str(log_dir / name))
                pulled += 1
        log.info(
            "log sync: pulled %d/%d logs from gs://%s/%s",
            pulled,
            len(LOG_FILES),
            settings.gcs_state_bucket,
            _GCS_PREFIX,
        )
    except Exception:  # noqa: BLE001 — boot must survive a bad bucket pull
        log.exception("log sync: failed pulling logs from GCS; starting from local state")


def persist_log(filename: str) -> None:
    """Upload one log file to GCS after an append. Best-effort no-op off GCS.

    Clobber guard (#165): these logs are append-only, so a correctly-synced
    local file only ever grows — it should never be smaller than the remote. If
    it is, this instance's copy is stale (e.g. a backfill ran elsewhere and
    grew the remote), and uploading would overwrite those newer rows. Refuse and
    log instead of shrinking the durable log. (Recover by re-syncing this
    instance — ``sync_logs_from_gcs`` / the reload-logs admin action.)
    """
    if not _enabled():
        return
    path = settings.data_dir / "logs" / filename
    if not path.exists():
        return
    try:
        bucket = _bucket()
        remote = bucket.get_blob(f"{_GCS_PREFIX}{filename}")  # None if absent; carries .size
        local_size = path.stat().st_size
        if remote is not None and (remote.size or 0) > local_size:
            log.warning(
                "log sync: refusing to shrink %s (local %d B < remote %d B) — this "
                "copy looks stale; skipping upload to avoid clobbering newer rows. "
                "Re-sync this instance (reload-logs) to recover.",
                filename, local_size, remote.size or 0,
            )
            return
        bucket.blob(f"{_GCS_PREFIX}{filename}").upload_from_filename(str(path))
    except Exception:  # noqa: BLE001 — a request must survive a bad bucket write
        log.exception(
            "log sync: failed uploading %s to GCS; next append will re-sync", filename
        )
