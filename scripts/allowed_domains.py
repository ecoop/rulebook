# Copyright (c) 2026 Eric Cooper.
"""Manage the GCS-backed per-user domain allowlist (#112).

The hosted deploy resolves ``token → allowed domains`` from an append-only
``allowed_domains.jsonl`` object (see rulebook.allowed_domains). This CLI is the
write side, and the home of the one-time **backfill** that makes existing
users' access EXPLICIT rather than relying on the resolver's default.

Needs STATE_BACKEND_KIND=gcs, GCS_STATE_BUCKET, and Application Default
Credentials (locally ``gcloud auth application-default login``):

    uv run python -m scripts.allowed_domains list
    uv run python -m scripts.allowed_domains set tok_abc123 --domains ultimate,goaltimate
    uv run python -m scripts.allowed_domains set tok_abc123 --all
    uv run python -m scripts.allowed_domains backfill --dry-run
    uv run python -m scripts.allowed_domains backfill            # writes explicit rows

`backfill` writes an explicit grant (default ``ultimate,goaltimate``, or
``--domains``) for every invite token that has NO grant row yet. It is
idempotent and ADD-ONLY: a token that already carries an explicit grant is left
untouched, so re-running is safe.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime

from rulebook.allowed_domains import (
    ALL_SENTINEL,
    append_allowed_domains_row,
    grants_from_rows,
    read_allowed_domains_rows,
)
from rulebook.tokens import read_tokens_object

DEFAULT_DOMAINS = ["ultimate", "goaltimate"]


def _require_gcs() -> str:
    if os.getenv("STATE_BACKEND_KIND", "local") != "gcs" or not os.getenv("GCS_STATE_BUCKET"):
        sys.exit("allowed_domains: needs STATE_BACKEND_KIND=gcs and GCS_STATE_BUCKET set.")
    return os.environ["GCS_STATE_BUCKET"]


def _sports_object() -> str:
    return os.getenv("RULEBOOK_ALLOWED_DOMAINS_OBJECT", "allowed_domains.jsonl")


def _invite_object() -> str:
    return os.getenv("RULEBOOK_INVITE_TOKENS_OBJECT", "invite_tokens.json")


def _parse_sports(args: argparse.Namespace) -> list[str] | str:
    if getattr(args, "all", False):
        return ALL_SENTINEL
    if args.domains:
        return [s.strip() for s in args.domains.split(",") if s.strip()]
    return list(DEFAULT_DOMAINS)


def _row(token: str, domains: list[str] | str, note: str) -> dict:
    return {
        "v": 1,
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "token": token,
        "domains": domains,
        "changed_by": "ops:allowed_domains",
        "note": note,
    }


def cmd_list(_args: argparse.Namespace) -> None:
    bucket = _require_gcs()
    grants = grants_from_rows(read_allowed_domains_rows(bucket, _sports_object()))
    tokens = read_tokens_object(bucket, _invite_object())
    if not tokens:
        print(f"(no invite tokens) gs://{bucket}/{_invite_object()}")
        return
    width = max(len(t) for t in tokens)
    for token, label in sorted(tokens.items(), key=lambda kv: kv[1]):
        g = grants.get(token)
        shown = "all (*)" if g == ALL_SENTINEL else (", ".join(g) if g else "— (no grant → default)")
        print(f"{token:<{width}}  {label:<16}  {shown}")


def cmd_set(args: argparse.Namespace) -> None:
    bucket = _require_gcs()
    domains = _parse_sports(args)
    append_allowed_domains_row(bucket, _sports_object(), _row(args.token, domains, "set via CLI"))
    shown = "all (*)" if domains == ALL_SENTINEL else ", ".join(domains) or "(none)"
    print(f"set: {args.token} → {shown}")


def cmd_backfill(args: argparse.Namespace) -> None:
    bucket = _require_gcs()
    domains = _parse_sports(args)
    grants = grants_from_rows(read_allowed_domains_rows(bucket, _sports_object()))
    tokens = read_tokens_object(bucket, _invite_object())
    missing = [(t, label) for t, label in sorted(tokens.items(), key=lambda kv: kv[1])
               if t not in grants]
    shown = "all (*)" if domains == ALL_SENTINEL else ", ".join(domains)
    if not missing:
        print(f"backfill: nothing to do — all {len(tokens)} user(s) already have an explicit grant.")
        return
    if args.dry_run:
        print(f"backfill --dry-run vs gs://{bucket}/{_sports_object()}:")
        print(f"  would grant [{shown}] to {len(missing)} ungranted user(s):")
        for t, label in missing:
            print(f"    {t}  ({label})")
        return
    for t, _label in missing:
        append_allowed_domains_row(bucket, _sports_object(), _row(t, domains, "backfill: made explicit"))
    print(f"backfill: wrote explicit [{shown}] grants for {len(missing)} user(s).")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="show each user's effective grant").set_defaults(func=cmd_list)

    p_set = sub.add_parser("set", help="grant one user an explicit domain allowlist")
    p_set.add_argument("token")
    p_set.add_argument("--domains", help="comma-separated domains, e.g. ultimate,goaltimate")
    p_set.add_argument("--all", action="store_true", help="grant all domains (incl. future)")
    p_set.set_defaults(func=cmd_set)

    p_bf = sub.add_parser("backfill", help="write explicit default grants for ungranted users")
    p_bf.add_argument("--domains", help=f"comma-separated domains (default {','.join(DEFAULT_DOMAINS)})")
    p_bf.add_argument("--all", action="store_true", help="grant all domains instead of the default")
    p_bf.add_argument("--dry-run", action="store_true", help="show what would change without writing")
    p_bf.set_defaults(func=cmd_backfill)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
