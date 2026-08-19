# Copyright (c) 2026 Eric Cooper.
"""Manage the GCS-backed domain registry (#113) — content config.

The registry (``domains.json``, a whole-object snapshot) declares each domain's
display name, source-download URLs, citation-numbering hint, and enabled flag.
It is authoritative for identity + enabled: a domain shows in the product only
if it's in the index AND enabled here. A domain absent from the registry
defaults to enabled with a title-cased name, so this CLI is only needed to
customize names/sources or to disable a domain.

Needs STATE_BACKEND_KIND=gcs, GCS_STATE_BUCKET, and Application Default
Credentials (locally ``gcloud auth application-default login``):

    uv run python -m scripts.domains list
    uv run python -m scripts.domains set ultimate --name "Ultimate (USAU)" \
        --sources https://usaultimate.org/rules --numbering "[{rule_id}]"
    uv run python -m scripts.domains disable badminton
    uv run python -m scripts.domains enable badminton
"""

from __future__ import annotations

import argparse
import os
import sys

from rulebook.registry import read_registry_object, write_registry_object

DEFAULT_OBJECT = "domains.json"


def _bucket_and_object() -> tuple[str, str]:
    if os.getenv("STATE_BACKEND_KIND", "local") != "gcs" or not os.getenv("GCS_STATE_BUCKET"):
        sys.exit("domains: needs STATE_BACKEND_KIND=gcs and GCS_STATE_BUCKET set.")
    return os.environ["GCS_STATE_BUCKET"], os.getenv("RULEBOOK_DOMAINS_OBJECT", DEFAULT_OBJECT)


def cmd_list(_args: argparse.Namespace) -> None:
    bucket, obj = _bucket_and_object()
    reg = read_registry_object(bucket, obj)
    if not reg:
        print(f"(empty) gs://{bucket}/{obj} — every indexed domain defaults to enabled.")
        return
    width = max(len(s) for s in reg)
    for slug, e in sorted(reg.items()):
        flag = "on " if e.get("enabled", True) else "OFF"
        name = e.get("display_name") or "(default name)"
        srcs = len(e.get("sources") or [])
        print(f"[{flag}] {slug:<{width}}  {name}  ({srcs} source url(s))")


def _upsert(bucket: str, obj: str, slug: str, changes: dict) -> dict:
    reg = read_registry_object(bucket, obj)
    entry = dict(reg.get(slug, {}))
    entry.update(changes)
    reg[slug] = entry
    write_registry_object(bucket, obj, reg)
    return entry


def cmd_set(args: argparse.Namespace) -> None:
    bucket, obj = _bucket_and_object()
    changes: dict = {}
    if args.name is not None:
        changes["display_name"] = args.name
    if args.sources is not None:
        changes["sources"] = [u.strip() for u in args.sources.split(",") if u.strip()]
    if args.numbering is not None:
        changes["numbering"] = args.numbering or None
    if not changes:
        sys.exit("domains set: nothing to change (pass --name/--sources/--numbering).")
    entry = _upsert(bucket, obj, args.slug, changes)
    print(f"set: {args.slug} → {entry}")


def cmd_enable(args: argparse.Namespace) -> None:
    bucket, obj = _bucket_and_object()
    _upsert(bucket, obj, args.slug, {"enabled": True})
    print(f"enabled: {args.slug}")


def cmd_disable(args: argparse.Namespace) -> None:
    bucket, obj = _bucket_and_object()
    _upsert(bucket, obj, args.slug, {"enabled": False})
    print(f"disabled: {args.slug} (hidden from the product until re-enabled)")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="show the registry").set_defaults(func=cmd_list)

    p_set = sub.add_parser("set", help="set a domain's display name / sources / numbering")
    p_set.add_argument("slug")
    p_set.add_argument("--name", help="display name, e.g. 'Ultimate (USAU)'")
    p_set.add_argument("--sources", help="comma-separated download URL(s)")
    p_set.add_argument("--numbering", help="citation-format hint, e.g. '[{rule_id}]'")
    p_set.set_defaults(func=cmd_set)

    p_en = sub.add_parser("enable", help="show this domain in the product")
    p_en.add_argument("slug")
    p_en.set_defaults(func=cmd_enable)

    p_dis = sub.add_parser("disable", help="hide this domain from the product")
    p_dis.add_argument("slug")
    p_dis.set_defaults(func=cmd_disable)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
