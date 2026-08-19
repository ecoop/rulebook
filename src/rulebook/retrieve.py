"""High-level retrieval — the layer between the vector store and the LLM.

Two flavors:

    retrieve(question, sport=None, k=5)
        Single-sport (or all-sports) top-k. Use for questions that are
        clearly about one sport: "what's the stall count in ultimate?".

    retrieve_across_sports(question, sports, k_per_sport=4)
        Retrieve k_per_sport results from EACH named sport, then combine.
        Use for comparison questions: "does either sport allow
        double-teaming?". The generator gets rules from every sport in
        context so it can genuinely compare rather than answering from
        whichever sport happened to dominate a single top-k.

We keep this layer deliberately thin. The "clever" happens either in
chunking (before) or in the prompt (after). Retrieval itself is dumb —
which makes it easy to reason about and easy to swap for something
smarter (reranking, hybrid BM25) later.

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
from .store import list_sports, open_store

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
    sport: str
    rule_id: str
    page_start: int
    page_end: int
    distance: float   # L2 distance on unit vectors; smaller = more similar


def _row_to_chunk(row: dict) -> RetrievedChunk:
    return RetrievedChunk(
        text=_normalize_ws(row["text"]),
        source=row["source"],
        sport=row["sport"],
        rule_id=row["rule_id"],
        page_start=int(row["page_start"]),
        page_end=int(row["page_end"]),
        distance=float(row["_distance"]),
    )


def retrieve(question: str, *, sport: str | None = None, k: int = 5) -> list[RetrievedChunk]:
    embedder = get_embedder()
    [q_vec] = embedder.embed([question], input_type="query")
    store = open_store(settings.resolved_index_path)
    rows = store.search(q_vec, k=k, sport=sport)
    return [_row_to_chunk(r) for r in rows]


# Cap on total passages returned across a cross-sport query, so N selected
# rulesets don't scale the model's context (and cost) by N. 1-2 sports at the
# default k_per_sport stay under it; larger unions get trimmed by breadth.
CROSS_SPORT_MAX_TOTAL = 12


def retrieve_across_sports(
    question: str,
    sports: list[str] | None = None,
    *,
    k_per_sport: int = 4,
    max_total: int = CROSS_SPORT_MAX_TOTAL,
) -> list[RetrievedChunk]:
    embedder = get_embedder()
    [q_vec] = embedder.embed([question], input_type="query")
    store = open_store(settings.resolved_index_path)
    # Default to every sport actually in the index (not a hardcoded list), so a
    # newly-added ruleset joins cross-sport comparison automatically.
    sports = list(sports or list_sports(settings.resolved_index_path))
    per_sport = [
        [_row_to_chunk(r) for r in store.search(q_vec, k=k_per_sport, sport=s)]
        for s in sports
    ]
    # Interleave by rank so every selected ruleset is represented, then cap the
    # total (round-robin: each sport's closest, then each sport's next, …). This
    # keeps 1-2 sports at the full per-sport k while stopping many rulesets from
    # blowing up the context — a global budget, weighted for breadth.
    combined: list[RetrievedChunk] = []
    for rank in range(k_per_sport):
        for chunks in per_sport:
            if rank < len(chunks):
                combined.append(chunks[rank])
                if len(combined) >= max_total:
                    return combined
    return combined
