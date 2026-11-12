"""High-level retrieval — the layer between the vector store and the LLM.

Two flavors:

    retrieve(question, domain=None, k=5)
        Single-domain (or all-domains) top-k. Use for questions that are
        clearly about one domain: "what's the stall count in ultimate?".

    retrieve_across_domains(question, domains, k_per_domain=4)
        Retrieve k_per_domain results from EACH named domain, then combine.
        Use for comparison questions: "does either domain allow
        double-teaming?". The generator gets rules from every domain in
        context so it can genuinely compare rather than answering from
        whichever domain happened to dominate a single top-k.

We keep this layer deliberately thin. The "clever" happens either in
chunking (before) or in the prompt (after). Retrieval itself is dumb —
which makes it easy to reason about and easy to swap for something
smarter. Reranking (src/rulebook/rerank.py) is that: when RERANK_PROVIDER
is set, retrieve() takes a wider candidate set and lets the reranker pick
the top k.

PERFORMANCE NOTE

    We open the store once per call. The store's load is O(N·D) reads
    plus a per-vector normalization; at our corpus size that's <5 ms and
    small enough not to bother caching. If this ever gets slow, cache
    the loaded Store in a module-level singleton behind a lock.
"""

import re
from dataclasses import dataclass

from .config import settings
from .embeddings import get_embedder
from .rerank import Reranker, get_reranker, reorder
from .store import list_domains, open_domain_store

_WHITESPACE_RUN = re.compile(r"\s+")


def _normalize_ws(text: str) -> str:
    """Collapse whitespace runs into single spaces.

    Some source PDFs extract as one word per line (``word\\n\\nword``),
    which is baked into the stored chunks. Left as-is it renders as a
    column of single words in the sources panel AND is what the model
    receives. Collapsing runs of whitespace here — the one seam every
    retrieved chunk passes through — cleans both the prompt context and
    the panel without rebuilding the index. (Rule ids come from the
    chunk header, not this text, so flattening structure is safe.)
    """
    return _WHITESPACE_RUN.sub(" ", text).strip()


@dataclass
class RetrievedChunk:
    text: str
    source: str
    domain: str
    rule_id: str
    page_start: int
    page_end: int
    distance: float   # squared L2 on unit vectors (2 - 2·cos); smaller = more similar


def _row_to_chunk(row: dict) -> RetrievedChunk:
    return RetrievedChunk(
        text=_normalize_ws(row["text"]),
        source=row["source"],
        domain=row["domain"],
        rule_id=row["rule_id"],
        page_start=int(row["page_start"]),
        page_end=int(row["page_end"]),
        distance=float(row["_distance"]),
    )


# Default for retrieve()'s ``reranker``: use whatever RERANK_PROVIDER selects.
FROM_SETTINGS = object()


def retrieve(
    question: str,
    *,
    domain: str,
    k: int = 5,
    reranker: Reranker | None | object = FROM_SETTINGS,
    candidates: int | None = None,
) -> list[RetrievedChunk]:
    """Top-k passages for ``question`` from ``domain``'s index.

    With a reranker (RERANK_PROVIDER, or passed in; ``None`` turns it off), the
    store returns ``candidates`` passages (default RERANK_CANDIDATES) and the
    reranker picks the top k from those. ``distance`` stays the embedding
    distance either way.
    """
    if reranker is FROM_SETTINGS:
        reranker = get_reranker()
    # Per-domain index (#128): each domain has its own store, so there's no
    # masking — the store IS the domain.
    embedder = get_embedder()
    [q_vec] = embedder.embed([question], input_type="query")
    store = open_domain_store(settings.resolved_index_path, domain)
    if reranker is None:
        return [_row_to_chunk(r) for r in store.search(q_vec, k=k)]
    n = max(k, candidates or settings.rerank_candidates)
    pool = [_row_to_chunk(r) for r in store.search(q_vec, k=n)]
    return reorder(question, pool, [c.text for c in pool], reranker)[:k]


# Cap on total passages returned across a cross-domain query, so N selected
# domains don't scale the model's context (and cost) by N. 1-2 domains at the
# default k_per_domain stay under it; larger unions get trimmed by breadth.
CROSS_DOMAIN_MAX_TOTAL = 12


def retrieve_across_domains(
    question: str,
    domains: list[str] | None = None,
    *,
    k_per_domain: int = 4,
    max_total: int = CROSS_DOMAIN_MAX_TOTAL,
) -> list[RetrievedChunk]:
    embedder = get_embedder()
    [q_vec] = embedder.embed([question], input_type="query")
    root = settings.resolved_index_path
    # Default to every BUILT domain (not a hardcoded list), so a newly-built
    # domain joins cross-domain comparison automatically. Per-domain (#128):
    # open each selected domain's own store rather than masking one big index.
    domains = list(domains or list_domains(root))
    per_domain = [
        [_row_to_chunk(r) for r in open_domain_store(root, s).search(q_vec, k=k_per_domain)]
        for s in domains
    ]
    # Interleave by rank so every selected domain is represented, then cap the
    # total (round-robin: each domain's closest, then each domain's next, …). This
    # keeps 1-2 domains at the full per-domain k while stopping many domains from
    # blowing up the context — a global budget, weighted for breadth.
    combined: list[RetrievedChunk] = []
    for rank in range(k_per_domain):
        for chunks in per_domain:
            if rank < len(chunks):
                combined.append(chunks[rank])
                if len(combined) >= max_total:
                    return combined
    return combined
