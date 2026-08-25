# Copyright (c) 2026 Eric Cooper.
"""Backfill an explicit `author` onto legacy gold answers.

Golds authored before guest-auth adoption carry `author: null`, so the Golds
tab and the build-history GOLDS popup show them as "—". At this point every such
gold was authored by a single person, so this one-time migration stamps a chosen
author label onto every gold that lacks one — making authorship explicit and
persisted before a question can accrue golds from *several* authors.

Golds are append-only, latest-per-gold_id wins, so re-running is safe and
idempotent (golds that already carry an author are skipped). The re-appended row
carries the gold's existing content AND its existing `domains` forward, so this
never undoes the #135 domain stamping (see scripts.gold_domains).

Needs STATE_BACKEND_KIND=gcs, GCS_STATE_BUCKET, and Application Default
Credentials:

    uv run python -m scripts.retag_author backfill --author Coop --dry-run
    uv run python -m scripts.retag_author backfill --author Coop
"""

from __future__ import annotations

import argparse
import os
import sys

from rulebook.interaction_log import log_gold, read_latest_golds
from rulebook.log_sync import sync_logs_from_gcs


def _require_gcs() -> None:
    if os.getenv("STATE_BACKEND_KIND", "local") != "gcs" or not os.getenv("GCS_STATE_BUCKET"):
        sys.exit("retag_author: needs STATE_BACKEND_KIND=gcs and GCS_STATE_BUCKET set.")


def cmd_backfill(args: argparse.Namespace) -> None:
    author = args.author.strip()
    if not author:
        sys.exit("retag_author: --author must be a non-empty label.")

    _require_gcs()
    print(f"retag_author: target bucket = gs://{os.environ['GCS_STATE_BUCKET']}/logs/  (verify this is prod's bucket)")
    sync_logs_from_gcs()  # pull the live gold.jsonl locally first

    golds = read_latest_golds()
    todo = [g for g in golds if not g.get("author")]
    if not todo:
        print(f"retag_author: nothing to do — all {len(golds)} gold(s) already have an author.")
        return

    if args.dry_run:
        print(f"backfill --dry-run: would stamp author={author!r} on {len(todo)} of {len(golds)} gold(s):")
        for g in todo:
            q = (g.get("question") or "")[:60]
            doms = ", ".join(g.get("domains") or []) or "(unstamped)"
            print(f"    {g['gold_id'][:8]}  [{doms}]   ({q})")
        return

    for g in todo:
        log_gold(
            g["qa_id"],
            gold_id=g["gold_id"],
            question=g.get("question", ""),
            gold_answer=g["gold_answer"],
            author=author,
            domains=g.get("domains"),  # carry #135's stamping forward
        )
    print(f"retag_author: stamped author={author!r} on {len(todo)} gold(s).")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_bf = sub.add_parser("backfill", help="stamp an author on golds that lack one")
    p_bf.add_argument("--author", required=True, help="the author label to stamp (e.g. Coop)")
    p_bf.add_argument("--dry-run", action="store_true", help="show what would change without writing")
    p_bf.set_defaults(func=cmd_backfill)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
