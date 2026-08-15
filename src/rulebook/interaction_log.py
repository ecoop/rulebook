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
from pathlib import Path
from typing import Any

from jsonl_log import append_jsonl, read_latest, read_latest_list, utc_now_iso

from .config import settings
from .log_sync import persist_log

# Schema version stamped into every row so readers can dispatch on
# `v` rather than sniffing the shape. Bump whenever the row format
# changes in a breaking way (add/remove field, rename, change type
# of an existing field). Purely additive backfills that keep old
# values valid can share a version.
#
# History (see feedback.jsonl.pre-migration-* backups):
#   v1  binary rating: {"rating": "up" | "down"}
#   v2  1-5 int rating + optional comment
#   v3  v2 + optional `tags` list
#   v4  v3 + optional `author` (guest-auth recipient label; null before adoption)
FEEDBACK_SCHEMA_VERSION = 4

# QA log — one row per /ask call.
#   v1  {qa_id, timestamp, question, sport, k, answer, chunks, input_tokens,
#        output_tokens, model}
#   v2  v1 + stop_reason from Anthropic ("end_turn", "max_tokens", ...)
#        so historical truncations are recoverable from the log.
#   v3  v2 + optional `author` (guest-auth recipient label; null before adoption)
QA_LOG_SCHEMA_VERSION = 3

# Gold answers — user-authored canonical answers, indexed as retrievable
# chunks on the next rebuild so future similar questions surface them.
#   v1  {qa_id, timestamp, question, gold_answer}
#   v2  v1 + optional `author` (guest-auth recipient label; null before adoption)
#   v3  v2 + `gold_id` — golds are OWNED entities now (docs/rbac-capabilities.md
#       §5): several golds can coexist per qa_id (different authors / clones), so
#       identity moves from qa_id to a per-gold id. Legacy rows (no gold_id)
#       resolve to gold_id == qa_id on read, so nothing needs migrating.
GOLD_SCHEMA_VERSION = 3

# Gold curation — admin decisions about whether a given gold should be
# included in the next index rebuild. Kept SEPARATE from gold.jsonl so
# gold stays "what the user authored" and curation stays "what the admin
# decided". Both are append-only; latest row per gold wins.
#   v1  {qa_id, included, timestamp}          (keyed by qa_id)
#   v2  {gold_id, included, timestamp}        (keyed by gold_id; legacy v1
#       rows key on qa_id == the legacy gold_id, so they still apply)
GOLD_CURATION_SCHEMA_VERSION = 2

# Source-file curation — admin decisions about whether a given source file
# under rules/<sport>/ is picked up by the next index rebuild. Same shape
# as gold curation but keyed by relative path.
#   v1  {path, included: bool, timestamp} (current)
SOURCE_CURATION_SCHEMA_VERSION = 1

# Audit trail — an append-only record of shared-state mutations (curate,
# clone, rebuild, user/role changes), so "who changed the shared system, and
# when" is answerable (docs/rbac-capabilities.md §5). Self-scoped writes
# (ratings, own golds) are already on the record via their own logs, so this
# captures only the actions that touch others' / shared state.
#   v1  {actor, action, target, detail, timestamp}
#   v2  v1 + actor_fingerprint — the 8-hex fingerprint of the actor's capability
#       set at the time (records "with what powers", survives role re-tuning)
AUDIT_SCHEMA_VERSION = 2

# Append + last-row-wins reads come from the shared `jsonl-log` library
# (jsonl_log.append_jsonl / read_latest / read_latest_list). It serializes
# writes under an in-process lock — the same single-process semantics the
# old local `_write_lock` gave; a real multi-worker deployment would still
# need file locking (fcntl.flock or a small append-service).


def _log_dir() -> Path:
    return settings.data_dir / "logs"


def _append(filename: str, row: dict[str, Any]) -> None:
    """Append one row to a log file, then write it through to GCS.

    A single seam so every logger persists consistently. ``persist_log`` is a
    no-op off the GCS backend, so local dev keeps plain file appends.
    """
    append_jsonl(_log_dir() / filename, row)
    persist_log(filename)


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
    author: str | None = None,
) -> None:
    """Record one /ask interaction (question in, answer + chunks out)."""
    _append(
        "qa_log.jsonl",
        {
            "v": QA_LOG_SCHEMA_VERSION,
            "qa_id": qa_id,
            "timestamp": utc_now_iso(timespec="auto", z=False),
            "question": question,
            "sport": sport,
            "k": k,
            "answer": answer,
            "chunks": chunks,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "model": model,
            "stop_reason": stop_reason,
            "author": author,
        },
    )


def log_gold(
    qa_id: str,
    *,
    gold_id: str,
    question: str,
    gold_answer: str,
    author: str | None = None,
) -> None:
    """Record a user-authored gold (canonical) answer, identified by gold_id.

    Append-only; the latest row per gold_id wins (editing a gold appends a new
    row with the same gold_id). Several golds can share a qa_id — different
    authors, or clones (docs/rbac-capabilities.md §5). Question text is
    duplicated from qa_log so gold.jsonl is self-contained for downstream
    consumers (the index
    builder, a future admin UI, etc).
    """
    _append(
        "gold.jsonl",
        {
            "v": GOLD_SCHEMA_VERSION,
            "gold_id": gold_id,
            "qa_id": qa_id,
            "timestamp": utc_now_iso(timespec="auto", z=False),
            "question": question,
            "gold_answer": gold_answer,
            "author": author,
        },
    )


def log_gold_curation(gold_id: str, *, included: bool) -> None:
    """Record an admin decision about whether a gold is included in the RAG
    index on the next rebuild.

    Append-only; latest row per gold_id wins. Absent-from-file is treated
    as "included by default" so a freshly-authored gold flows into the
    index without an admin having to approve it first.
    """
    _append(
        "gold_curation.jsonl",
        {
            "v": GOLD_CURATION_SCHEMA_VERSION,
            "gold_id": gold_id,
            "timestamp": utc_now_iso(timespec="auto", z=False),
            "included": included,
        },
    )


def _read_gold_rows() -> list[dict[str, Any]]:
    """All gold rows, each with a resolved `gold_id` (legacy rows: == qa_id).

    Read raw rather than via read_latest_list because the key is computed
    (gold_id-or-qa_id) — jsonl_log keys on a fixed field name, which can't
    express the legacy fallback.
    """
    path = _log_dir() / "gold.jsonl"
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            row["gold_id"] = row.get("gold_id") or row["qa_id"]
            rows.append(row)
    return rows


def read_latest_golds() -> list[dict[str, Any]]:
    """Latest gold row per gold_id, sorted newest-first.

    Legacy rows (no gold_id) key on their qa_id, preserving the old
    one-gold-per-qa_id history; new golds carry a distinct gold_id so several
    can coexist per qa_id. Empty list if the log doesn't exist yet.
    """
    latest: dict[str, dict[str, Any]] = {}
    for row in _read_gold_rows():  # append-only file → last write wins
        latest[row["gold_id"]] = row
    return sorted(latest.values(), key=lambda r: r.get("timestamp", ""), reverse=True)


def read_latest_curation() -> dict[str, bool]:
    """Return {gold_id: included} for the latest curation row per gold.

    Legacy curation rows key on qa_id, which equals the legacy gold_id, so
    they still apply. Absent gold_ids default to included=True at the call
    site — this function just reports what the log says, no defaulting.
    """
    path = _log_dir() / "gold_curation.jsonl"
    if not path.exists():
        return {}
    latest: dict[str, bool] = {}
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            key = row.get("gold_id") or row["qa_id"]
            latest[key] = bool(row["included"])
    return latest


def read_latest_feedback() -> list[dict[str, Any]]:
    """Return the latest feedback event per qa_id, sorted newest-first.

    Multiple rows per qa_id exist by design (each click/save is its own
    event). For the admin digest we only care about the current state,
    so we walk the file, keep last-write-wins per qa_id, and sort by
    timestamp. Empty list if the file doesn't exist yet.
    """
    # Skip legacy v1 rows (rating is a string) — they were binary up/down
    # test data and don't fit the tag/comment schema the digest UI expects.
    return read_latest_list(
        _log_dir() / "feedback.jsonl",
        "qa_id",
        where=lambda r: not isinstance(r.get("rating"), str),
        sort_desc="timestamp",
    )


def read_qa_questions() -> dict[str, str]:
    """Return {qa_id: question} from qa_log.jsonl. Empty if no log yet."""
    latest = read_latest(_log_dir() / "qa_log.jsonl", "qa_id")
    return {qa_id: row.get("question", "") for qa_id, row in latest.items()}


def count_questions_by_author() -> dict[str, int]:
    """Lifetime question counts keyed by author (guest-auth recipient label).

    One qa_id == one asked question, so we tally distinct qa_id rows per
    author. Rows with no author (pre-adoption / anonymous) are skipped.
    Powers the Users tab's "# questions" column.
    """
    latest = read_latest(_log_dir() / "qa_log.jsonl", "qa_id")
    counts: dict[str, int] = {}
    for row in latest.values():
        author = row.get("author")
        if author:
            counts[author] = counts.get(author, 0) + 1
    return counts


def count_comments_by_author() -> dict[str, int]:
    """Per-author count of distinct answers they've left a comment on.

    Feedback is append-only with several rows per qa_id (each save is an
    event) and is keyed by qa_id alone — so a later rating by a *different*
    user would hide an earlier comment. To count fairly we keep the latest
    row per ``(qa_id, author)`` (dedupes self-edits, survives others'
    ratings) and tally authors whose latest row carries a non-empty comment.
    """
    path = _log_dir() / "feedback.jsonl"
    if not path.exists():
        return {}
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            author, qa_id = row.get("author"), row.get("qa_id")
            if author and qa_id:
                latest[(qa_id, author)] = row  # last write wins per pair
    counts: dict[str, int] = {}
    for (_qa_id, author), row in latest.items():
        comment = row.get("comment")
        if comment and str(comment).strip():
            counts[author] = counts.get(author, 0) + 1
    return counts


def count_golds_by_author() -> dict[str, int]:
    """Per-author count of gold answers they own (latest row per gold_id)."""
    counts: dict[str, int] = {}
    for row in read_latest_golds():
        author = row.get("author")
        if author:
            counts[author] = counts.get(author, 0) + 1
    return counts


INDEX_BUILDS_LOG = "index_builds.jsonl"


def log_index_build(record: dict[str, Any]) -> None:
    """Append one index-build record (its manifest provenance) to the durable
    build history that powers the Indices tab. Append-only, one row per build;
    persists to GCS like the other logs."""
    _append(INDEX_BUILDS_LOG, record)


def read_index_builds(limit: int | None = None) -> list[dict[str, Any]]:
    """All recorded index builds, newest first. Empty until the first build
    under the history-logging path runs."""
    path = _log_dir() / INDEX_BUILDS_LOG
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    rows.reverse()  # appended in build order → newest first
    return rows[:limit] if limit is not None else rows


def log_source_curation(source_path: str, *, included: bool) -> None:
    """Record an admin decision about a source file's inclusion.

    ``source_path`` is repo-relative, posix-style
    (e.g. ``rules/ultimate/strategy.md``). Same append-only semantics
    as gold curation: latest row per path wins.
    """
    _append(
        "source_curation.jsonl",
        {
            "v": SOURCE_CURATION_SCHEMA_VERSION,
            "path": source_path,
            "timestamp": utc_now_iso(timespec="auto", z=False),
            "included": included,
        },
    )


def read_latest_source_curation() -> dict[str, bool]:
    """Return {path: included} for the latest source-curation row per path.

    Absent paths default to included=True at the call site.
    """
    latest = read_latest(_log_dir() / "source_curation.jsonl", "path")
    return {path: bool(row["included"]) for path, row in latest.items()}


def log_audit(
    *,
    actor: str | None,
    action: str,
    target: str | None = None,
    detail: dict[str, Any] | None = None,
    actor_fingerprint: str | None = None,
) -> None:
    """Append one row to the audit trail for a shared-state mutation.

    `actor` is the guest recipient label, `action` the capability the write
    exercised (e.g. "golds.curate"), `target` the affected id (gold_id, source
    path, token…), `detail` any before→after specifics, `actor_fingerprint` the
    8-hex fingerprint of the actor's capability set at the time. Append-only;
    every row is kept (this is the record, not a latest-wins state).
    """
    _append(
        "audit.jsonl",
        {
            "v": AUDIT_SCHEMA_VERSION,
            "timestamp": utc_now_iso(timespec="auto", z=False),
            "actor": actor,
            "actor_fingerprint": actor_fingerprint,
            "action": action,
            "target": target,
            "detail": detail or {},
        },
    )


def read_audit(limit: int | None = None) -> list[dict[str, Any]]:
    """Return audit rows, newest-first (optionally capped at `limit`)."""
    path = _log_dir() / "audit.jsonl"
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    rows.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return rows[:limit] if limit is not None else rows


def log_feedback(
    qa_id: str,
    *,
    rating: int,
    comment: str | None = None,
    tags: list[str] | None = None,
    author: str | None = None,
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
    _append(
        "feedback.jsonl",
        {
            "v": FEEDBACK_SCHEMA_VERSION,
            "qa_id": qa_id,
            "timestamp": utc_now_iso(timespec="auto", z=False),
            "rating": rating,
            "tags": list(tags or []),
            "comment": comment or None,
            "author": author,
        },
    )
