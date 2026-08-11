# Copyright (c) 2026 Eric Cooper.
"""Manage the GCS-backed invite allowlist without a redeploy.

The hosted deploy reads ``{token: label}`` from a GCS object per request
(see rulebook.tokens). This CLI is the write side — add, list, or remove
users, taking effect within the source's TTL (~30s) across every running
instance. It's also the seam the Stage 3 "Users" UI will call.

    uv run python -m scripts.invite_tokens list
    uv run python -m scripts.invite_tokens add "alice"        # mints tok_...
    uv run python -m scripts.invite_tokens add "bob" --token tok_custom
    uv run python -m scripts.invite_tokens rm tok_abc123

Targets $GCS_STATE_BUCKET / $RULEBOOK_INVITE_TOKENS_OBJECT (default
invite_tokens.json). Requires STATE_BACKEND_KIND=gcs and Application
Default Credentials with objectAdmin on the bucket — locally, a one-time
``gcloud auth application-default login``.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys

from rulebook.tokens import read_tokens_object, write_tokens_object


def _bucket_and_object() -> tuple[str, str]:
    # Read straight from env rather than the full Settings object — this is
    # an ops tool and shouldn't require ANTHROPIC_API_KEY (or any generation
    # config) just to add a user. Same env vars the deploy uses.
    if os.getenv("STATE_BACKEND_KIND", "local") != "gcs" or not os.getenv(
        "GCS_STATE_BUCKET"
    ):
        sys.exit(
            "invite_tokens: needs STATE_BACKEND_KIND=gcs and GCS_STATE_BUCKET set."
        )
    bucket = os.environ["GCS_STATE_BUCKET"]
    obj = os.getenv("RULEBOOK_INVITE_TOKENS_OBJECT", "invite_tokens.json")
    return bucket, obj


def _mint() -> str:
    # Opaque, URL-safe, tok_-prefixed for readability in logs/cookies.
    return "tok_" + secrets.token_urlsafe(16)


def cmd_list(_args: argparse.Namespace) -> None:
    bucket, obj = _bucket_and_object()
    tokens = read_tokens_object(bucket, obj)
    if not tokens:
        print(f"(empty) gs://{bucket}/{obj}")
        return
    width = max(len(t) for t in tokens)
    for token, label in sorted(tokens.items(), key=lambda kv: kv[1]):
        print(f"{token:<{width}}  {label}")


def cmd_add(args: argparse.Namespace) -> None:
    bucket, obj = _bucket_and_object()
    tokens = read_tokens_object(bucket, obj)
    token = args.token or _mint()
    if token in tokens:
        sys.exit(f"invite_tokens: {token} already exists ({tokens[token]!r}).")
    tokens[token] = args.label
    write_tokens_object(bucket, obj, tokens)
    print(f"added: {token}  →  {args.label}")
    print(f"invite link: https://<host>/?token={token}")


def cmd_rm(args: argparse.Namespace) -> None:
    bucket, obj = _bucket_and_object()
    tokens = read_tokens_object(bucket, obj)
    if args.token not in tokens:
        sys.exit(f"invite_tokens: {args.token} not found.")
    label = tokens.pop(args.token)
    write_tokens_object(bucket, obj, tokens)
    print(f"removed: {args.token} ({label})")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="show the current allowlist").set_defaults(func=cmd_list)

    p_add = sub.add_parser("add", help="add a user (mints a token unless --token)")
    p_add.add_argument("label", help="recipient label, e.g. 'alice'")
    p_add.add_argument("--token", help="use a specific token instead of minting one")
    p_add.set_defaults(func=cmd_add)

    p_rm = sub.add_parser("rm", help="remove a user by token")
    p_rm.add_argument("token")
    p_rm.set_defaults(func=cmd_rm)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
