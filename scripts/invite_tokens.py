# Copyright (c) 2026 Eric Cooper.
"""Manage the GCS-backed invite allowlist.

The hosted deploy reads ``{token: label}`` from a GCS object per request
(see rulebook.tokens). This CLI is the write side — changes take effect
within the source's TTL (~30s) across every running instance. It's also
the seam the "Users" tab calls.

Direct GCS commands (need STATE_BACKEND_KIND=gcs, GCS_STATE_BUCKET, and
Application Default Credentials — locally ``gcloud auth application-default
login``):

    uv run python -m scripts.invite_tokens list
    uv run python -m scripts.invite_tokens add "alice"        # mints tok_...
    uv run python -m scripts.invite_tokens add "bob" --token tok_custom
    uv run python -m scripts.invite_tokens rm tok_abc123

Batch, file-driven flow — keep a local (gitignored) record of name↔token,
then push it live. `gen` is offline (no GCS); only `push` touches the bucket:

    uv run python -m scripts.invite_tokens gen            # names → local JSON + links
    uv run python -m scripts.invite_tokens push --dry-run # preview
    uv run python -m scripts.invite_tokens push           # upsert into the live allowlist

`gen` reads one name per line from secrets/demo_guests.txt and writes
secrets/invite_tokens.local.json ({token: label}, your source of truth) plus
secrets/invite_links.md. It MERGES — a name already in the JSON keeps its
token, so shared links never break. `push` is ADD-ONLY: it upserts every
local entry and never deletes a token that only exists live (e.g. one an
admin added via the Users tab).
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path

from rulebook.tokens import read_tokens_object, write_tokens_object

DEFAULT_NAMES = "secrets/demo_guests.txt"
DEFAULT_LOCAL = "secrets/invite_tokens.local.json"
DEFAULT_LINKS = "secrets/invite_links.md"
DEFAULT_BASE_URL = "https://rulebook.cooper.nu"


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


def _read_names(path: Path) -> list[str]:
    names: list[str] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        names.append(line)
    return names


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


def cmd_gen(args: argparse.Namespace) -> None:
    """Mint tokens for names in a local file. Offline — never touches GCS."""
    names_path = Path(args.names)
    out_path = Path(args.out)
    links_path = Path(args.links)

    if not names_path.exists():
        names_path.parent.mkdir(parents=True, exist_ok=True)
        names_path.write_text(
            "# One recipient per line. Blank lines and #comments are ignored.\n"
            "# Re-run `gen` after editing; names already minted keep their token.\n"
            "# e.g.\n# Eric\n# Alice\n"
        )
        sys.exit(f"created template {names_path} — add one name per line, then re-run `gen`.")

    names = _read_names(names_path)
    if not names:
        sys.exit(f"{names_path} has no names (blank/comment-only).")

    # {token: label}; reverse map to keep a known name's existing token.
    existing: dict[str, str] = {}
    if out_path.exists():
        existing = json.loads(out_path.read_text())
    name_to_token = {label: tok for tok, label in existing.items()}

    result = dict(existing)
    minted = 0
    for name in names:
        if name in name_to_token:
            continue  # preserve the existing token — don't break shared links
        token = _mint()
        result[token] = name
        name_to_token[name] = token
        minted += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")

    md = ["# Invite links", "", f"_Base: {args.base_url}_", ""]
    for token, name in sorted(result.items(), key=lambda kv: kv[1].lower()):
        md.append(f"- **{name}** — {args.base_url}/?token={token}")
    links_path.write_text("\n".join(md) + "\n")

    print(
        f"gen: {len(names)} name(s) in {names_path.name}; minted {minted} new, "
        f"{len(result)} total."
    )
    print(f"  tokens → {out_path}")
    print(f"  links  → {links_path}")


def cmd_push(args: argparse.Namespace) -> None:
    """Upsert the local token file into the live allowlist (add-only)."""
    src = Path(args.src)
    if not src.exists():
        sys.exit(f"{src} not found — run `gen` first.")
    local: dict[str, str] = json.loads(src.read_text())
    if not local:
        sys.exit(f"{src} is empty.")

    bucket, obj = _bucket_and_object()
    live = read_tokens_object(bucket, obj)

    added = [n for t, n in local.items() if t not in live]
    updated = [n for t, n in local.items() if t in live and live[t] != n]
    unchanged = [n for t, n in local.items() if live.get(t) == n]

    if args.dry_run:
        print(f"push --dry-run vs gs://{bucket}/{obj}:")
        print(
            f"  add {len(added)}, update {len(updated)}, unchanged {len(unchanged)}; "
            f"live {len(live)} now → {len(set(live) | set(local))} after."
        )
        return

    merged = dict(live)
    merged.update(local)  # add-only upsert; never removes a live-only token
    write_tokens_object(bucket, obj, merged)
    print(
        f"push: +{len(added)} added, {len(updated)} updated, {len(unchanged)} unchanged "
        f"→ gs://{bucket}/{obj} ({len(merged)} total)."
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="show the current live allowlist").set_defaults(func=cmd_list)

    p_add = sub.add_parser("add", help="add one user live (mints a token unless --token)")
    p_add.add_argument("label", help="recipient label, e.g. 'alice'")
    p_add.add_argument("--token", help="use a specific token instead of minting one")
    p_add.set_defaults(func=cmd_add)

    p_rm = sub.add_parser("rm", help="remove one user live, by token")
    p_rm.add_argument("token")
    p_rm.set_defaults(func=cmd_rm)

    p_gen = sub.add_parser("gen", help="mint tokens for a local names file (offline, no GCS)")
    p_gen.add_argument("--names", default=DEFAULT_NAMES, help=f"input, one name/line (default {DEFAULT_NAMES})")
    p_gen.add_argument("--out", default=DEFAULT_LOCAL, help=f"local {{token: label}} JSON (default {DEFAULT_LOCAL})")
    p_gen.add_argument("--links", default=DEFAULT_LINKS, help=f"generated invite-links markdown (default {DEFAULT_LINKS})")
    p_gen.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"link base (default {DEFAULT_BASE_URL})")
    p_gen.set_defaults(func=cmd_gen)

    p_push = sub.add_parser("push", help="upsert the local token file into the live allowlist (add-only)")
    p_push.add_argument("--from", dest="src", default=DEFAULT_LOCAL, help=f"local JSON to push (default {DEFAULT_LOCAL})")
    p_push.add_argument("--dry-run", action="store_true", help="show what would change without writing")
    p_push.set_defaults(func=cmd_push)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
