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
from typing import Any, Literal

from .config import settings

Rating = Literal["up", "down"]

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
) -> None:
    """Record one /ask interaction (question in, answer + chunks out)."""
    _append_jsonl(
        _log_dir() / "qa_log.jsonl",
        {
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
        },
    )


def log_feedback(qa_id: str, *, rating: Rating) -> None:
    """Record a thumbs-up / thumbs-down vote against a specific qa_id."""
    _append_jsonl(
        _log_dir() / "feedback.jsonl",
        {
            "qa_id": qa_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "rating": rating,
        },
    )
