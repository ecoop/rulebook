"""Build the RAG index from the PDFs under ./Rules.

Run:
    uv run python scripts/build_index.py

Pipeline per source:
    PDF file -> ingest.extract_pages -> chunking.chunk_pages
        -> embeddings.embed(input_type="document")
        -> store.write_store

Idempotent: rewrites the index from scratch every time. That's the safe
default when your chunking or embedding model might change — a partial
rebuild would leave old vectors in an inconsistent state next to the new
ones and retrieval quality would silently degrade.

Adding a sport is a two-line change to SOURCES below.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tqdm import tqdm

from ulty_goalty.chunking import Chunk, chunk_pages
from ulty_goalty.config import settings
from ulty_goalty.embeddings import get_embedder
from ulty_goalty.ingest import extract_pages
from ulty_goalty.store import write_store


@dataclass
class Source:
    sport: str
    pdf: Path


SOURCES = [
    Source(sport="ultimate", pdf=Path("Rules/2026-27-Official-Rules-of-Ultimate.pdf")),
    Source(sport="goaltimate", pdf=Path("Rules/usag-rule-v-2-1-3.pdf")),
]

# Embed in batches so we play nice with the embedder's request-size limits
# and get a useful progress bar. Voyage caps requests at 1000 items or
# ~120k tokens per call; 64 is well under both for our chunk sizes.
EMBED_BATCH_SIZE = 64


def main() -> None:
    repo_root = settings.repo_root

    all_chunks: list[Chunk] = []
    for src in SOURCES:
        pdf_path = src.pdf if src.pdf.is_absolute() else repo_root / src.pdf
        if not pdf_path.exists():
            raise FileNotFoundError(f"Missing rulebook: {pdf_path}")

        print(f"[ingest]  {src.sport}: reading {pdf_path.name}")
        pages = extract_pages(pdf_path)
        print(f"          -> {len(pages)} pages of text")

        chunks = chunk_pages(pages, source=pdf_path.name, sport=src.sport)
        print(f"[chunk ]  {src.sport}: {len(chunks)} chunks "
              f"(avg {sum(len(c.text) for c in chunks) // max(len(chunks), 1)} chars)")

        all_chunks.extend(chunks)

    if not all_chunks:
        raise RuntimeError("No chunks produced — check the PDFs.")

    embedder = get_embedder()
    print(f"[embed ]  provider={settings.embedding_provider} "
          f"model={settings.embedding_model}  ({len(all_chunks)} chunks)")

    vectors: list[list[float]] = []
    for i in tqdm(range(0, len(all_chunks), EMBED_BATCH_SIZE), desc="  embedding batches"):
        batch = all_chunks[i : i + EMBED_BATCH_SIZE]
        vectors.extend(
            embedder.embed([c.text for c in batch], input_type="document")
        )

    written = write_store(
        settings.resolved_index_path,
        all_chunks,
        vectors,
        provider=settings.embedding_provider,
        model=settings.embedding_model,
    )
    print(f"[store ]  wrote {written} rows to {settings.resolved_index_path}")
    print(f"[done  ]  index dimension = {len(vectors[0])}")


if __name__ == "__main__":
    main()
