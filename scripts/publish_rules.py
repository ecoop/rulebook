# Copyright (c) 2026 Eric Cooper.
"""Upload the local rules/ corpus to the GCS state bucket (#170).

The container no longer bakes the rule PDFs into its image; it syncs them from
``gs://<bucket>/rules/`` at runtime (``rules_sync``). Seed that prefix from the
local ``rules/`` dir with this script — once to migrate, and again whenever the
corpus changes.

Needs STATE_BACKEND_KIND=gcs, GCS_STATE_BUCKET, and Application Default
Credentials:

    STATE_BACKEND_KIND=gcs GCS_STATE_BUCKET=<STATE_BUCKET> \
        uv run python -m scripts.publish_rules --dry-run
    STATE_BACKEND_KIND=gcs GCS_STATE_BUCKET=<STATE_BUCKET> \
        uv run python -m scripts.publish_rules
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from rulebook.rules_sync import _SUFFIXES, publish_rules_to_gcs

# The operator's local corpus is the repo's rules/, NOT settings.rules_dir
# (which under gcs points at the container's writable sync dir).
REPO_RULES = Path(__file__).resolve().parent.parent / "rules"


def _require_gcs() -> None:
    if os.getenv("STATE_BACKEND_KIND", "local") != "gcs" or not os.getenv("GCS_STATE_BUCKET"):
        sys.exit("publish_rules: needs STATE_BACKEND_KIND=gcs and GCS_STATE_BUCKET set.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="list files without uploading")
    parser.add_argument(
        "--source", type=Path, default=REPO_RULES,
        help=f"local rules dir to upload (default: {REPO_RULES})",
    )
    args = parser.parse_args(argv)

    _require_gcs()
    print(f"publish_rules: target bucket = gs://{os.environ['GCS_STATE_BUCKET']}/rules/  (verify this is the right bucket)")

    root: Path = args.source
    if not root.is_dir():
        sys.exit(f"publish_rules: source dir {root} does not exist.")

    files = [p for p in sorted(root.rglob("*")) if p.is_file() and p.suffix.lower() in _SUFFIXES]
    if not files:
        sys.exit(f"publish_rules: no {' / '.join(_SUFFIXES)} files under {root}.")

    if args.dry_run:
        total = sum(p.stat().st_size for p in files)
        print(f"--dry-run: would upload {len(files)} file(s) ({total / 1_048_576:.1f} MiB) from {root}:")
        for p in files:
            print(f"    rules/{p.relative_to(root).as_posix()}")
        return

    n = publish_rules_to_gcs(source_dir=root)
    print(f"publish_rules: uploaded {n} file(s) to gs://{os.environ['GCS_STATE_BUCKET']}/rules/")


if __name__ == "__main__":
    main()
