# Copyright (c) 2026 Eric Cooper.
"""Retrieval evaluation: hit@k and MRR over a labeled gold set.

Retrieval is the half of RAG you can measure *without* an LLM in the loop: given
a question whose answer you know lives in rule X, did the retriever surface rule
X, and how near the top? Two classic metrics, computed here from scratch so you
can see exactly what they are — no black-box eval dependency:

    hit@k   Did any acceptable gold rule land in the top k? A per-question yes/no,
            averaged over the set. "Is the answer even in the context window?"

    MRR     Mean Reciprocal Rank: 1/(rank of the first gold hit), averaged. Gold
            at rank 1 → 1.0, rank 2 → 0.5, rank 3 → 0.33, not found → 0. Unlike
            hit@k it cares *where* the answer landed, which is what matters when
            the generator leans on the first passage or two. (We compute both
            within the same top-k retrieve, so read them as hit@k and MRR@k.)

WHY THIS LIVES IN THE APP, not just a notebook: it's a real capability — point it
at any built domain and get a number. The CLI (`python -m rulebook.eval`) and the
teaching notebook both call `evaluate()`, so there's one source of truth and the
notebook can't drift from what the app actually does.

HOW YOU USE IT. The honest payoff is comparing embedders: build the index with
the local model, run this; set EMBEDDING_PROVIDER=voyage, rebuild, run it again.
The delta in hit@k/MRR is the embedder upgrade expressed as a number instead of a
vibe. On a small, clean corpus the two may tie — which is itself the lesson: you
now have evidence, not a guess, and you'll see the gap grow on a harder corpus.
For local models there's a shortcut: ``build_scratch_index(domain, model)`` embeds a
domain into a throwaway store, so several models can be scored side by side with
``evaluate(..., index=...)`` without touching the real index.

THE GOLD SET. One JSONL file per domain under eval/gold/<domain>.jsonl, one
question per line:

    {"domain": "checkers", "question": "How does a king move?",
     "gold": ["4.2"], "style": "literal"}

`gold` is the list of acceptable rule_ids — retrieving ANY of them counts as a
hit (a question can have more than one right passage). `style` ("literal" vs
"paraphrase") is optional and only drives the by-style breakdown; paraphrased
questions, which don't reuse the rule's wording, are where a weak embedder
actually shows its seams. Labeling is the real cost of evaluation: ~a dozen
hand-written questions per domain is enough to be useful.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .chunking import chunk_pages
from .config import settings
from .embeddings import LocalEmbedder
from .ingest import extract_pages
from .retrieve import retrieve
from .store import Store, write_store


def gold_dir() -> Path:
    """Where the committed gold sets live (eval/gold/ under the repo root)."""
    return settings.repo_root / "eval" / "gold"


@dataclass(frozen=True)
class GoldItem:
    domain: str
    question: str
    gold: tuple[str, ...]  # acceptable rule_ids; retrieving ANY of them is a hit
    style: str = ""        # "literal" | "paraphrase" | "" — optional, for slicing


def load_gold(domain: str | None = None, *, directory: Path | None = None) -> list[GoldItem]:
    """Load gold items from eval/gold/*.jsonl, optionally filtered to one domain."""
    directory = directory or gold_dir()
    files = (
        [directory / f"{domain}.jsonl"] if domain else sorted(directory.glob("*.jsonl"))
    )
    items: list[GoldItem] = []
    for path in files:
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            items.append(
                GoldItem(
                    domain=row["domain"],
                    question=row["question"],
                    gold=tuple(row["gold"]),
                    style=row.get("style", ""),
                )
            )
    return items


def hit_at_k(retrieved_ids: list[str], gold: tuple[str, ...], k: int) -> bool:
    """Did any acceptable gold id appear in the top-k retrieved ids?"""
    top = retrieved_ids[:k]
    return any(g in top for g in gold)


def reciprocal_rank(retrieved_ids: list[str], gold: tuple[str, ...]) -> float:
    """1/(rank of the first gold hit), 1-indexed; 0.0 if none are present."""
    for rank, rid in enumerate(retrieved_ids, start=1):
        if rid in gold:
            return 1.0 / rank
    return 0.0


@dataclass
class ItemResult:
    item: GoldItem
    retrieved_ids: list[str]
    hit: bool
    rr: float


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


@dataclass
class EvalResult:
    k: int
    items: list[ItemResult] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.items)

    @property
    def hit_rate(self) -> float:
        return _mean([1.0 if r.hit else 0.0 for r in self.items])

    @property
    def mrr(self) -> float:
        return _mean([r.rr for r in self.items])

    def hit_rate_at(self, k: int) -> float:
        """hit@k for any k up to the k these results were retrieved at."""
        if k > self.k:
            raise ValueError(f"retrieved only the top {self.k}; can't score hit@{k}")
        return _mean(
            [1.0 if hit_at_k(r.retrieved_ids, r.item.gold, k) else 0.0 for r in self.items]
        )

    def by_style(self) -> dict[str, tuple[int, float, float]]:
        """{style: (n, hit_rate, mrr)} for each style present — slices easy vs hard."""
        styles = sorted({r.item.style for r in self.items})
        out: dict[str, tuple[int, float, float]] = {}
        for s in styles:
            group = [r for r in self.items if r.item.style == s]
            out[s or "(unlabeled)"] = (
                len(group),
                _mean([1.0 if r.hit else 0.0 for r in group]),
                _mean([r.rr for r in group]),
            )
        return out


@dataclass
class ScratchIndex:
    """One domain embedded with one LOCAL model, in a throwaway store.

    For side-by-side embedder comparisons: build one per model, then pass it as
    ``index=`` to :func:`evaluate` or :func:`rank_of`. The store lives in a temp
    directory, so the real index under ``data/index`` is never touched.
    """

    domain: str
    model: str
    embedder: LocalEmbedder
    store: Store


_SOURCE_SUFFIXES = {".pdf", ".md", ".txt"}  # the same suffixes build_index.py ingests


def build_scratch_index(domain: str, model: str) -> ScratchIndex:
    """Chunk a domain's rule docs and embed them with a local model2vec ``model``.

    Rule documents only (no gold-answer chunks), which is all the sample domains
    have. The first call for a model downloads it once (tens of MB) and caches it.
    """
    docs = sorted(
        p
        for p in (settings.rules_dir / domain).iterdir()
        if p.is_file() and p.suffix.lower() in _SOURCE_SUFFIXES
    )
    chunks = [
        c for d in docs for c in chunk_pages(extract_pages(d), source=d.name, domain=domain)
    ]
    embedder = LocalEmbedder(model)
    vectors = embedder.embed([c.text for c in chunks], input_type="document")
    path = Path(tempfile.mkdtemp(prefix=f"rulebook-scratch-{domain}-"))
    write_store(path, chunks, vectors, provider="local", model=model)
    return ScratchIndex(domain=domain, model=model, embedder=embedder, store=Store(path).load())


def _retrieved_ids(
    question: str, domain: str, k: int, index: ScratchIndex | None
) -> list[str]:
    """Top-k rule_ids from the built index — or from ``index`` when one is given."""
    if index is None:
        return [c.rule_id for c in retrieve(question, domain=domain, k=k)]
    if domain != index.domain:
        raise ValueError(f"scratch index is for {index.domain!r}, not {domain!r}")
    [q_vec] = index.embedder.embed([question], input_type="query")
    return [row["rule_id"] for row in index.store.search(q_vec, k=k)]


def rank_of(
    question: str,
    gold: tuple[str, ...],
    *,
    domain: str | None = None,
    k: int = 5,
    index: ScratchIndex | None = None,
) -> int | None:
    """1-indexed rank of the first acceptable gold rule in the top-k; None if absent."""
    if index is not None:
        if domain is not None and domain != index.domain:
            raise ValueError(f"scratch index is for {index.domain!r}, not {domain!r}")
        domain = index.domain
    if domain is None:
        raise ValueError("rank_of needs a domain (or a scratch index)")
    rr = reciprocal_rank(_retrieved_ids(question, domain, k, index), gold)
    return round(1 / rr) if rr else None


def evaluate(
    items: list[GoldItem], *, k: int = 5, index: ScratchIndex | None = None
) -> EvalResult:
    """Retrieve top-k for each gold question and score hit@k + reciprocal rank.

    By default this searches the built index for each item's domain, so it needs
    that index built with the active embedder (a mismatched provider compares
    different geometries and the numbers are meaningless). Pass ``index`` to
    search a :class:`ScratchIndex` instead — handy for comparing local models
    without rebuilding anything. Retrieval errors propagate; the CLI checks
    which domains are built before calling this.
    """
    result = EvalResult(k=k)
    for item in items:
        rids = _retrieved_ids(item.question, item.domain, k, index)
        result.items.append(
            ItemResult(
                item=item,
                retrieved_ids=rids,
                hit=hit_at_k(rids, item.gold, k),
                rr=reciprocal_rank(rids, item.gold),
            )
        )
    return result


# --- CLI: `python -m rulebook.eval [--domain X] [-k N]` ----------------------


def _first_hit(ids: list[str], gold: tuple[str, ...]) -> str:
    for rid in ids:
        if rid in gold:
            return rid
    return "—"


def _print_domain(domain: str, res: EvalResult) -> None:
    from .store import domain_index_path, read_manifest

    mf = read_manifest(domain_index_path(settings.resolved_index_path, domain))
    index_desc = f"{mf.get('provider', '?')}/{mf.get('model', '?')}"
    print(f"\n━━ {domain} ━━  index: {index_desc}  n={res.n}  k={res.k}")

    # The index must have been built by the embedder we're now querying with —
    # otherwise query and stored vectors live in different geometries and the
    # scores are noise. Warn loudly rather than silently reporting garbage.
    if mf and (
        mf.get("provider") != settings.embedding_provider
        or mf.get("model") != settings.embedding_model
    ):
        print(
            f"   ! WARNING: index was built with {index_desc} but EMBEDDING_PROVIDER="
            f"{settings.embedding_provider}/{settings.embedding_model} is active.\n"
            f"   ! Rebuild the index for this provider before trusting these numbers."
        )

    print(f"   hit@{res.k} = {res.hit_rate:.3f}   MRR@{res.k} = {res.mrr:.3f}")
    for style, (n, hr, mrr) in res.by_style().items():
        print(f"   {style:<12} n={n:<3} hit@{res.k}={hr:.3f}  MRR={mrr:.3f}")
    for r in res.items:
        mark = "✓" if r.hit else "✗"
        top = ",".join(r.retrieved_ids[:5]) or "(none)"
        print(
            f"   {mark} {r.rr:.2f} [{_first_hit(r.retrieved_ids, r.item.gold):>3}]  "
            f"{r.item.question[:52]:<52}  gold={','.join(r.item.gold)}  top={top}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m rulebook.eval",
        description="Score retrieval (hit@k, MRR) against the labeled gold set.",
    )
    parser.add_argument("--domain", help="evaluate only this domain (default: all with gold + a built index)")
    parser.add_argument("-k", type=int, default=5, help="top-k to retrieve (default: 5)")
    args = parser.parse_args(argv)

    from . import app_state
    from .store import list_domains

    app_state.initialize(settings)

    items = load_gold(args.domain)
    if not items:
        where = f" for domain {args.domain!r}" if args.domain else ""
        print(f"error: no gold items found{where} under {gold_dir()}.", file=sys.stderr)
        return 1

    built = set(list_domains(settings.resolved_index_path))
    domains = sorted({it.domain for it in items})
    overall = EvalResult(k=args.k)
    evaluated = 0
    for domain in domains:
        if domain not in built:
            print(
                f"\n━━ {domain} ━━  (skipped: no index built — run "
                f"`python -m rulebook.add {domain} ...` or scripts/build_index.py)"
            )
            continue
        res = evaluate([it for it in items if it.domain == domain], k=args.k)
        _print_domain(domain, res)
        overall.items.extend(res.items)
        evaluated += 1

    if evaluated == 0:
        print("\nNo domains with both gold and a built index — nothing evaluated.", file=sys.stderr)
        return 1
    if evaluated > 1:
        print(
            f"\n══ overall ══  domains={evaluated}  n={overall.n}  "
            f"hit@{overall.k}={overall.hit_rate:.3f}  MRR@{overall.k}={overall.mrr:.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
