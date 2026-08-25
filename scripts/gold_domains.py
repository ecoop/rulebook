# Copyright (c) 2026 Eric Cooper.
"""Backfill explicit `domains` onto existing gold answers (#135).

A gold with no `## Domain` headings used to fan into every domain's index. Now a
gold indexes only into the domains it NAMES. This one-time migration resolves and
**persists** each existing gold's domains NOW — while "all" unambiguously means
the legacy set (ultimate+goaltimate) — so it's frozen instead of recomputed
against a growing "all" later.

Resolution per gold (see rulebook.gold_domains): `## Domain` sections ▸ the
originating qa_log row's frozen list ▸ the configured legacy set. Writes a new
gold row (same gold_id + content) with `domains` stamped; golds are append-only,
latest-per-gold_id wins, so re-running is safe and idempotent (golds that already
carry `domains` are skipped).

Needs STATE_BACKEND_KIND=gcs, GCS_STATE_BUCKET, and Application Default
Credentials:

    uv run python -m scripts.gold_domains backfill --dry-run
    uv run python -m scripts.gold_domains backfill
"""

from __future__ import annotations

import argparse
import os
import sys

from rulebook.config import settings
from rulebook.gold_domains import gold_target_domains
from rulebook.interaction_log import log_gold, read_latest_golds, read_qa_entries
from rulebook.log_sync import sync_logs_from_gcs
from rulebook.registry import declared_domains
from rulebook.store import list_domains


def _require_gcs() -> None:
    if os.getenv("STATE_BACKEND_KIND", "local") != "gcs" or not os.getenv("GCS_STATE_BUCKET"):
        sys.exit("gold_domains: needs STATE_BACKEND_KIND=gcs and GCS_STATE_BUCKET set.")


def _known() -> set[str]:
    # Faithful stamp: legacy ∪ built ∪ registry-declared, so a resolved domain
    # isn't dropped just because it isn't built at migration time.
    return (
        set(settings.gold_legacy_domains)
        | set(list_domains(settings.resolved_index_path))
        | set(declared_domains())
    )


def cmd_backfill(args: argparse.Namespace) -> None:
    _require_gcs()
    print(f"gold_domains: target bucket = gs://{os.environ['GCS_STATE_BUCKET']}/logs/  (verify this is prod's bucket)")
    sync_logs_from_gcs()  # pull the live gold.jsonl + qa_log.jsonl locally first

    golds = read_latest_golds()
    qa_index = {r["qa_id"]: r for r in read_qa_entries()}
    known = _known()
    legacy = settings.gold_legacy_domains

    todo = [g for g in golds if not g.get("domains")]
    if not todo:
        print(f"gold_domains: nothing to do — all {len(golds)} gold(s) already stamped.")
        return

    if args.dry_run:
        print(f"backfill --dry-run: would stamp {len(todo)} of {len(golds)} gold(s):")
        for g in todo:
            target = gold_target_domains(g, qa_index, legacy=legacy, known=known)
            q = (g.get("question") or "")[:60]
            print(f"    {g['gold_id'][:8]}  → {', '.join(target) or '(none)'}   ({q})")
        return

    for g in todo:
        target = gold_target_domains(g, qa_index, legacy=legacy, known=known)
        log_gold(
            g["qa_id"],
            gold_id=g["gold_id"],
            question=g.get("question", ""),
            gold_answer=g["gold_answer"],
            author=g.get("author"),
            domains=target,
        )
    print(f"gold_domains: stamped explicit domains on {len(todo)} gold(s).")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_bf = sub.add_parser("backfill", help="stamp explicit domains on golds that lack them")
    p_bf.add_argument("--dry-run", action="store_true", help="show what would change without writing")
    p_bf.set_defaults(func=cmd_backfill)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
