"""Append-only JSONL log for /ask requests and their feedback.

Two files, both under data/logs/:

    qa_log.jsonl        one line per /ask call
    feedback.jsonl      one line per user rating on a specific answer

Kept as two files (rather than one file with a "kind" discriminator) so:

    * The QA log stays truly append-only — no read/modify/write cycle.
    * Feedback can arrive minutes after the question was asked, or the
      user can change their vote. We append every event; the "current"
      rating for a qa_id is the last row for that qa_id.
    * Each file can be inspected or piped separately without filtering.

RATIONALE

    This is the raw material for the next feature the user wants to
    build: a "corrected-answer" retrieval store where downvoted answers
    get replaced with a user-authored fix that then becomes an
    indexable chunk. That's a natural next step once we know which
    answers were poor — which is what this log lets us learn.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from .config import settings

# Schema version stamped into every row so readers can dispatch on
# `v` rather than sniffing the shape. Bump whenever the row format
# changes in a breaking way (add/remove field, rename, change type
# of an existing field). Purely additive backfills that keep old
# values valid can share a version.
#
# History (see feedback.jsonl.pre-migration-* backups):
#   v1  binary rating: {"rating": "up" | "down"}
#   v2  1-5 int rating + optional comment
#   v3  v2 + optional `tags` list (current)
FEEDBACK_SCHEMA_VERSION = 3

# QA log — one row per /ask call.
#   v1  {qa_id, timestamp, question, sport, k, answer, chunks, input_tokens,
#        output_tokens, model}
#   v2  v1 + stop_reason from Anthropic ("end_turn", "max_tokens", ...)
#        so historical truncations are recoverable from the log. (current)
QA_LOG_SCHEMA_VERSION = 2

# Gold answers — user-authored canonical answers, indexed as retrievable
# chunks on the next rebuild so future similar questions surface them.
#   v1  {qa_id, timestamp, question, gold_answer} (current)
GOLD_SCHEMA_VERSION = 1

# Gold curation — admin decisions about whether a given gold should be
# included in the next index rebuild. Kept SEPARATE from gold.jsonl so
# gold stays "what the user authored" and curation stays "what the admin
# decided". Both are append-only; latest row per qa_id wins.
#   v1  {qa_id, included: bool, timestamp} (current)
GOLD_CURATION_SCHEMA_VERSION = 1

# Source-file curation — admin decisions about whether a given source file
# under rules/<sport>/ is picked up by the next index rebuild. Same shape
# as gold curation but keyed by relative path.
#   v1  {path, included: bool, timestamp} (current)
SOURCE_CURATION_SCHEMA_VERSION = 1

# Serialize appends so concurrent requests can't interleave partial writes.
# JSONL requires one complete object per line — a raced write would corrupt
# the file for downstream readers. Uvicorn --reload runs one process by
# default, so an in-process lock suffices; a real multi-worker deployment
# would need file locking (fcntl.flock or a small append-service).
_write_lock = Lock()


def _log_dir() -> Path:
    return settings.repo_root / "data" / "logs"


def _append_jsonl(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False) + "\n"
    with _write_lock, path.open("a", encoding="utf-8") as f:
        f.write(line)


def log_qa(
    qa_id: str,
    *,
    question: str,
    sport: str | None,
    k: int,
    answer: str,
    chunks: list[dict[str, Any]],
    input_tokens: int,
    output_tokens: int,
    model: str,
    stop_reason: str,
) -> None:
    """Record one /ask interaction (question in, answer + chunks out)."""
    _append_jsonl(
        _log_dir() / "qa_log.jsonl",
        {
            "v": QA_LOG_SCHEMA_VERSION,
            "qa_id": qa_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "question": question,
            "sport": sport,
            "k": k,
            "answer": answer,
            "chunks": chunks,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "model": model,
            "stop_reason": stop_reason,
        },
    )


def log_gold(qa_id: str, *, question: str, gold_answer: str) -> None:
    """Record a user-authored gold (canonical) answer for a qa_id.

    Same append-only semantics as feedback: multiple rows per qa_id are
    allowed and the latest wins. Question text is duplicated from qa_log
    so gold.jsonl is self-contained for downstream consumers (the index
    builder, a future admin UI, etc).
    """
    _append_jsonl(
        _log_dir() / "gold.jsonl",
        {
            "v": GOLD_SCHEMA_VERSION,
            "qa_id": qa_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "question": question,
            "gold_answer": gold_answer,
        },
    )


def log_gold_curation(qa_id: str, *, included: bool) -> None:
    """Record an admin decision about whether a gold answer is included in
    the RAG index on the next rebuild.

    Append-only; latest row per qa_id wins. Absent-from-file is treated
    as "included by default" so a freshly-authored gold flows into the
    index without an admin having to approve it first.
    """
    _append_jsonl(
        _log_dir() / "gold_curation.jsonl",
        {
            "v": GOLD_CURATION_SCHEMA_VERSION,
            "qa_id": qa_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "included": included,
        },
    )


def read_latest_golds() -> list[dict[str, Any]]:
    """Return the latest gold row per qa_id, sorted newest-first.

    Empty list if the log doesn't exist yet.
    """
    path = _log_dir() / "gold.jsonl"
    if not path.exists():
        return []
    latest: dict[str, dict] = {}
    for line in path.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            latest[row["qa_id"]] = row
    return sorted(latest.values(), key=lambda r: r["timestamp"], reverse=True)


def read_latest_curation() -> dict[str, bool]:
    """Return {qa_id: included} for the latest curation row per qa_id.

    Absent qa_ids default to included=True at the call site — this
    function just reports what the log says, no defaulting.
    """
    path = _log_dir() / "gold_curation.jsonl"
    if not path.exists():
        return {}
    latest: dict[str, bool] = {}
    for line in path.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            latest[row["qa_id"]] = bool(row["included"])
    return latest


def log_source_curation(source_path: str, *, included: bool) -> None:
    """Record an admin decision about a source file's inclusion.

    ``source_path`` is repo-relative, posix-style
    (e.g. ``rules/ultimate/strategy.md``). Same append-only semantics
    as gold curation: latest row per path wins.
    """
    _append_jsonl(
        _log_dir() / "source_curation.jsonl",
        {
            "v": SOURCE_CURATION_SCHEMA_VERSION,
            "path": source_path,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "included": included,
        },
    )


def read_latest_source_curation() -> dict[str, bool]:
    """Return {path: included} for the latest source-curation row per path.

    Absent paths default to included=True at the call site.
    """
    path = _log_dir() / "source_curation.jsonl"
    if not path.exists():
        return {}
    latest: dict[str, bool] = {}
    for line in path.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            latest[row["path"]] = bool(row["included"])
    return latest


def log_feedback(
    qa_id: str,
    *,
    rating: int,
    comment: str | None = None,
    tags: list[str] | None = None,
) -> None:
    """Record a 1-5 rating, issue tags, and an optional note.

    Multiple rows per qa_id are expected — refining a note, toggling
    tags, or changing the rating all append a new event. Readers should
    take the last row per qa_id as the "current" state.

    Tags are a small, action-oriented taxonomy of what went wrong (or
    right) — see the frontend for the current vocabulary. Stored as-is
    with no validation here so the vocabulary can evolve without a
    logfile migration.
    """
    _append_jsonl(
        _log_dir() / "feedback.jsonl",
        {
            "v": FEEDBACK_SCHEMA_VERSION,
            "qa_id": qa_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "rating": rating,
            "tags": list(tags or []),
            "comment": comment or None,
        },
    )
