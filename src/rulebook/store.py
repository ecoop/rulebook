"""In-memory numpy vector store with disk-backed persistence.

For a corpus this small (hundreds, not millions, of chunks) a real vector
DB is overkill. NumPy does everything we need: cosine similarity is a
matrix multiplication, top-k is an argsort. Fewer moving parts means
fewer things to debug and a lot more transparency into what "vector
search" actually IS at the arithmetic level.

PERSISTENCE

    Everything lives in one directory (settings.index_path) as three files:

        vectors.npy    float32 [N, D] array, one row per chunk
        chunks.jsonl   one JSON object per row, SAME ORDER as vectors
        manifest.json  provider, model, count, dimension, sports — for
                       sanity checks and human inspection

    Nice properties of this layout:
      * The metadata is diffable in git if you ever want to commit it.
      * You can `cat manifest.json` to see what's in your index without
        writing a lick of code.
      * Rebuilding an index is `rm -rf` + `python scripts/build_index.py`.

SEARCH

    On load we normalize every stored vector to unit length. Voyage and
    OpenAI already return unit vectors, but explicit normalization means:
      * cosine similarity = plain dot product (numerically cleaner),
      * swapping in a non-normalizing embedder later doesn't silently
        break ranking.

    For queries we normalize the query vector, take the dot product
    against the stored matrix (one big matmul), argsort descending, and
    return the top-k rows. The sport filter is applied by masking the
    metadata list BEFORE the matmul, so a filtered search doesn't waste
    work on other sports.

    We report `_distance` on returned rows as L2 distance on unit
    vectors (which equals 2 - 2·cos_sim). The field name matches the
    convention used by LanceDB and friends, so downstream code doesn't
    care what backend it's talking to.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path

import numpy as np

from .chunking import Chunk

VECTORS_FILE = "vectors.npy"
CHUNKS_FILE = "chunks.jsonl"
MANIFEST_FILE = "manifest.json"


class Store:
    """Load-once, query-many wrapper around vectors + metadata on disk."""

    def __init__(self, path: Path):
        self.path = path
        self.vectors: np.ndarray | None = None
        self.metadata: list[dict] = []
        self.manifest: dict = {}

    def load(self) -> "Store":
        if not (self.path / VECTORS_FILE).exists():
            # Empty store — leave vectors=None so search() raises clearly
            # if someone queries before building the index.
            return self

        vecs = np.load(self.path / VECTORS_FILE).astype(np.float32, copy=False)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self.vectors = vecs / norms

        with (self.path / CHUNKS_FILE).open() as f:
            self.metadata = [json.loads(line) for line in f]

        with (self.path / MANIFEST_FILE).open() as f:
            self.manifest = json.load(f)

        assert len(self.metadata) == self.vectors.shape[0], (
            f"metadata rows ({len(self.metadata)}) != vector rows "
            f"({self.vectors.shape[0]}) at {self.path}"
        )
        return self

    def search(
        self,
        query_vector: list[float] | np.ndarray,
        *,
        k: int = 5,
        sport: str | None = None,
    ) -> list[dict]:
        if self.vectors is None:
            raise RuntimeError(
                f"No index at {self.path}. Build it with "
                f"`uv run python scripts/build_index.py`."
            )

        q = np.asarray(query_vector, dtype=np.float32)
        q = q / max(float(np.linalg.norm(q)), 1e-12)

        if sport is not None:
            mask_ix = np.array(
                [i for i, m in enumerate(self.metadata) if m["sport"] == sport],
                dtype=np.int64,
            )
            if mask_ix.size == 0:
                return []
            sims = self.vectors[mask_ix] @ q
            top_rel = np.argsort(-sims)[:k]
            picked = mask_ix[top_rel]
            sims_picked = sims[top_rel]
        else:
            sims = self.vectors @ q
            picked = np.argsort(-sims)[:k]
            sims_picked = sims[picked]

        out = []
        for row_ix, sim in zip(picked.tolist(), sims_picked.tolist(), strict=True):
            row = dict(self.metadata[row_ix])
            # L2 on unit vectors. Lower = more similar, same convention
            # as LanceDB so retrieve.py's naming stays stable if we swap.
            row["_distance"] = float(2.0 - 2.0 * sim)
            out.append(row)
        return out


def open_store(path: Path) -> Store:
    path.mkdir(parents=True, exist_ok=True)
    return Store(path).load()


def write_store(
    path: Path,
    chunks: Iterable[Chunk],
    vectors: Iterable[list[float]],
    *,
    provider: str,
    model: str,
) -> int:
    """Persist chunks + vectors to disk. Returns rows written.

    This is a full replace, not an append — build_index is the canonical
    caller and it always rebuilds from scratch. Keeping the semantics
    simple avoids the "why is this old chunk still in results?" trap.
    """
    path.mkdir(parents=True, exist_ok=True)

    chunk_list = list(chunks)
    vec_list = list(vectors)
    if len(chunk_list) != len(vec_list):
        raise ValueError(
            f"chunks/vectors length mismatch: {len(chunk_list)} vs {len(vec_list)}"
        )

    for name in (VECTORS_FILE, CHUNKS_FILE, MANIFEST_FILE):
        (path / name).unlink(missing_ok=True)

    arr = np.asarray(vec_list, dtype=np.float32)
    np.save(path / VECTORS_FILE, arr)

    with (path / CHUNKS_FILE).open("w") as f:
        for c in chunk_list:
            f.write(json.dumps(asdict(c)) + "\n")

    with (path / MANIFEST_FILE).open("w") as f:
        json.dump(
            {
                "provider": provider,
                "model": model,
                "count": len(chunk_list),
                "dimension": int(arr.shape[1]) if arr.size else 0,
                "sports": sorted({c.sport for c in chunk_list}),
            },
            f,
            indent=2,
        )

    return len(chunk_list)


def count_rows(path: Path) -> int:
    if not (path / CHUNKS_FILE).exists():
        return 0
    with (path / CHUNKS_FILE).open() as f:
        return sum(1 for _ in f)


def list_sports(path: Path) -> list[str]:
    if not (path / MANIFEST_FILE).exists():
        return []
    with (path / MANIFEST_FILE).open() as f:
        return json.load(f).get("sports", [])
