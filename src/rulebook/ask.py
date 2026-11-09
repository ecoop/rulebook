# Copyright (c) 2026 Eric Cooper.
"""Command-line `ask`: retrieval + answer, with the internals shown.

    uv run python -m rulebook.ask "how do you win at checkers?"
    uv run python -m rulebook.ask "does cornhole use forced captures?" --domain cornhole
    uv run python -m rulebook.ask "how is each game won?" --domains checkers,cornhole

This is the smallest possible front door to the pipeline — no web server, no
React build. It prints the retrieved chunks *with their similarity distances*
and then the generated answer, so you can see exactly what the model was given
and how the two relate. That transparency is the whole point of it for someone
learning RAG: the product UI hides the distances; this doesn't.

Needs your keys in `.env` (ANTHROPIC_API_KEY for generation, an embedding key
for retrieval) and a built index — run `scripts/build_index.py` or
`python -m rulebook.add` first.
"""

from __future__ import annotations

import argparse
import sys

from . import app_state
from .config import settings
from .pipeline import ask


def _print_chunks(chunks) -> None:
    """Show what retrieval handed the model: closest (smallest distance) first."""
    if not chunks:
        print("  (no chunks retrieved — is the index built for this domain?)")
        return
    for i, c in enumerate(chunks, 1):
        pages = (
            f"p.{c.page_start}"
            if c.page_start == c.page_end
            else f"pp.{c.page_start}-{c.page_end}"
        )
        # distance is L2 on unit vectors (0 = identical, 2 = opposite); lower is nearer.
        print(f"  {i}. [{c.domain} {c.rule_id} — {pages}]  distance={c.distance:.3f}")
        snippet = c.text if len(c.text) <= 160 else c.text[:157] + "..."
        print(f"       {snippet}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m rulebook.ask",
        description="Ask a rules question from the command line and see the retrieved passages.",
    )
    parser.add_argument("question", help="the natural-language question (quote it)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--domain",
        help="retrieve from ONLY this domain (single-domain mode)",
    )
    group.add_argument(
        "--domains",
        help="comma-separated domains to compare (cross-domain mode); default: all built",
    )
    parser.add_argument(
        "-k", type=int, default=5, help="top-k passages to retrieve (default: 5)"
    )
    args = parser.parse_args(argv)

    # Same guardrail singletons the API server and build_index construct — the
    # generation call records usage through them, so they must exist first.
    app_state.initialize(settings)

    domains = (
        [d.strip() for d in args.domains.split(",") if d.strip()]
        if args.domains
        else None
    )

    try:
        result = ask(args.question, domain=args.domain, domains=domains, k=args.k)
    except RuntimeError as e:
        # The store raises a clear "no index at ..." message; surface it plainly.
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(f"\nQUESTION\n  {result.question}\n")
    print(f"RETRIEVED (top {args.k}{' per domain' if domains else ''})")
    _print_chunks(result.chunks)
    print(f"\nANSWER\n  {result.answer}\n")
    if result.unverified_citations:
        print(
            "NOTE: the answer cited passages that were NOT retrieved "
            f"(unverified): {', '.join(result.unverified_citations)}"
        )
    print(
        f"tokens: {result.input_tokens} in / {result.output_tokens} out  "
        f"(stop_reason={result.stop_reason})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
