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

from dataclasses import dataclass

from .config import settings
from .embeddings import get_embedder
from .store import open_store


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
        text=row["text"],
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


def retrieve_across_sports(
    question: str,
    sports: list[str],
    *,
    k_per_sport: int = 4,
) -> list[RetrievedChunk]:
    embedder = get_embedder()
    [q_vec] = embedder.embed([question], input_type="query")
    store = open_store(settings.resolved_index_path)
    combined: list[RetrievedChunk] = []
    for s in sports:
        rows = store.search(q_vec, k=k_per_sport, sport=s)
        combined.extend(_row_to_chunk(r) for r in rows)
    return combined
