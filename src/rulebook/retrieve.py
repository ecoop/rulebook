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

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from .config import settings
from .embeddings import get_embedder
from .rerank import Reranker, get_reranker, reorder
from .store import Store, list_domains, open_domain_store

log = logging.getLogger(__name__)

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
    # Squared L2 on unit vectors (2 - 2·cos); smaller = more similar. None for a
    # passage that wasn't retrieved by similarity: a linked definition.
    distance: float | None
    # The term, when this passage is a definition added for one (definitions.py).
    defines: str | None = None


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


class EmbedderMismatchError(RuntimeError):
    """A domain's index was built by a different embedder than the one configured.

    A question is only comparable with the stored chunks if the same model
    embedded both. A different model can give vectors of a different length (a
    shape error) or of the same length in an unrelated space (nearest neighbours
    that mean nothing), so retrieval refuses rather than return either.
    """


# Index dirs already warned about having no recorded model, so a long-running
# app logs it once per index rather than on every question.
_warned_unknown_embedder: set[Path] = set()


def _open_for_query(root: Path, domain: str) -> Store:
    """Open ``domain``'s store, checking it was built by the configured embedder.

    Raises :class:`EmbedderMismatchError` when the manifest's provider/model differ
    from EMBEDDING_PROVIDER/EMBEDDING_MODEL. An index whose manifest records no
    model (built before manifests carried one) is searched as-is, with a warning.
    Scratch indexes (eval.build_scratch_index) don't come through here: they carry
    their own embedder.
    """
    store = open_domain_store(root, domain)
    if store.vectors is None:
        return store  # unbuilt; search() raises its own "build the index" error
    built_provider = store.manifest.get("provider")
    built_model = store.manifest.get("model")
    if built_model is None:
        if store.path not in _warned_unknown_embedder:
            _warned_unknown_embedder.add(store.path)
            log.warning(
                "Index for %r records no embedding model; assuming it matches "
                "%s/%s. Rebuild it to record one: "
                "uv run python scripts/build_index.py --domain %s",
                domain, settings.embedding_provider, settings.embedding_model, domain,
            )
        return store
    if (built_provider, built_model) != (settings.embedding_provider, settings.embedding_model):
        raise EmbedderMismatchError(
            f"The {domain!r} index was built with {built_provider}/{built_model}, "
            f"but the configured embedder is "
            f"{settings.embedding_provider}/{settings.embedding_model} "
            f"(EMBEDDING_PROVIDER / EMBEDDING_MODEL). Questions must be embedded by "
            f"the same model as the index. Rebuild it with "
            f"`uv run python scripts/build_index.py --domain {domain}`, "
            f"or set the embedder back to {built_provider}/{built_model}."
        )
    return store


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
    # Check the index before embedding, so a mismatch costs no embedding call.
    store = _open_for_query(settings.resolved_index_path, domain)
    embedder = get_embedder()
    [q_vec] = embedder.embed([question], input_type="query")
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
    root = settings.resolved_index_path
    # Default to every BUILT domain (not a hardcoded list), so a newly-built
    # domain joins cross-domain comparison automatically. Per-domain (#128):
    # open each selected domain's own store rather than masking one big index.
    domains = list(domains or list_domains(root))
    stores = [_open_for_query(root, s) for s in domains]
    embedder = get_embedder()
    [q_vec] = embedder.embed([question], input_type="query")
    per_domain = [
        [_row_to_chunk(r) for r in store.search(q_vec, k=k_per_domain)]
        for store in stores
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
