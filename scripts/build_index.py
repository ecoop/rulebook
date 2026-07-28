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

import json
import re
from dataclasses import dataclass
from pathlib import Path

from tqdm import tqdm

from rulebook.chunking import Chunk, chunk_pages
from rulebook.config import settings
from rulebook.embeddings import get_embedder
from rulebook.ingest import extract_pages
from rulebook.interaction_log import read_latest_curation
from rulebook.pipeline import DEFAULT_SPORTS
from rulebook.store import write_store


@dataclass
class Source:
    sport: str
    # PDF (born-digital) or a Markdown/text file (e.g. output from
    # scripts/vision_extract.py for image-only PDFs). Both are handled
    # transparently by ingest.extract_pages.
    path: Path


SOURCES = [
    Source(sport="ultimate", path=Path("rules/2026-27-Official-Rules-of-Ultimate.pdf")),
    Source(sport="goaltimate", path=Path("rules/usag-rule-v-2-1-3.pdf")),
    # Image-only field diagram — text extracted by vision_extract.py.
    Source(sport="goaltimate", path=Path("rules/goaltimate-field-setupregulation2017.extracted.md")),
]

# Embed in batches so we play nice with the embedder's request-size limits
# and get a useful progress bar. Voyage caps requests at 1000 items or
# ~120k tokens per call; 64 is well under both for our chunk sizes.
EMBED_BATCH_SIZE = 64

# User-authored gold answers, appended by POST /gold. Optional — if the
# file doesn't exist yet (no golds saved), we skip cleanly.
GOLD_LOG = Path("data/logs/gold.jsonl")

# Section-heading pattern for splitting a gold answer into per-sport
# chunks. Matches a line beginning with "## Ultimate" or "## Goaltimate"
# (case-insensitive). If a gold answer has no such headings, the whole
# text becomes one chunk tagged with every known sport (so it retrieves
# for any sport-filtered query).
_SPORT_HEADING = re.compile(r"^\s*##\s+([A-Za-z][A-Za-z_ -]*?)\s*$", re.M)


def load_gold_chunks(gold_path: Path) -> list[Chunk]:
    """Turn user-authored gold answers into per-sport retrievable chunks.

    Gold answers are append-only in gold.jsonl (latest row per qa_id
    wins). Each surviving gold is split on ``## Sport`` headings; each
    section becomes one Chunk tagged with that sport. Sections whose
    heading isn't a recognized sport are ignored. A gold answer with no
    matching headings falls back to one shared chunk per known sport so
    the content still retrieves under any sport filter.

    Chunk metadata is chosen so citations read clearly downstream:
        rule_id = f"user-gold-{qa_id[:8]}"
        source  = "gold.jsonl"
        page    = 0 (no meaningful page for user text)
    """
    if not gold_path.exists():
        return []

    # Latest row per qa_id wins — walk the file and keep last-write-wins.
    latest: dict[str, dict] = {}
    with gold_path.open() as f:
        for line in f:
            row = json.loads(line)
            latest[row["qa_id"]] = row

    # Apply admin curation: skip golds whose latest curation row set
    # included=False. Absent from the curation log = included by default,
    # so freshly-authored golds flow into the index automatically.
    curation = read_latest_curation()
    excluded = {qa_id for qa_id, included in curation.items() if not included}
    if excluded:
        latest = {qa_id: row for qa_id, row in latest.items() if qa_id not in excluded}
        print(f"[curate]  {len(excluded)} gold(s) excluded by admin")

    known = set(DEFAULT_SPORTS)
    chunks: list[Chunk] = []
    for qa_id, row in latest.items():
        text = row["gold_answer"].strip()
        if not text:
            continue

        sections = _split_by_sport_heading(text, known)
        if not sections:
            # No sport headings — index once per sport so the whole
            # gold is retrievable under any sport filter.
            for sport in known:
                chunks.append(
                    Chunk(
                        source="gold.jsonl",
                        sport=sport,
                        rule_id=f"user-gold-{qa_id[:8]}",
                        page_start=0,
                        page_end=0,
                        text=text,
                    )
                )
            continue

        for sport, section_text in sections:
            chunks.append(
                Chunk(
                    source="gold.jsonl",
                    sport=sport,
                    rule_id=f"user-gold-{qa_id[:8]}",
                    page_start=0,
                    page_end=0,
                    text=section_text,
                )
            )
    return chunks


def _split_by_sport_heading(text: str, known_sports: set[str]) -> list[tuple[str, str]]:
    """Return [(sport, section_text)] for each ``## Sport`` section.

    Sports whose heading isn't in known_sports are dropped (protects
    against noise headings like ``## Shared`` — that content is
    currently discarded; if we later want a "both sports" bucket we'd
    duplicate its text into every known sport here).
    """
    matches = list(_SPORT_HEADING.finditer(text))
    if not matches:
        return []

    sections: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        sport = m.group(1).strip().lower()
        if sport not in known_sports:
            continue
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section_text = text[start:end].strip()
        if section_text:
            sections.append((sport, section_text))
    return sections


def main() -> None:
    repo_root = settings.repo_root

    all_chunks: list[Chunk] = []
    for src in SOURCES:
        src_path = src.path if src.path.is_absolute() else repo_root / src.path
        if not src_path.exists():
            raise FileNotFoundError(f"Missing source: {src_path}")

        print(f"[ingest]  {src.sport}: reading {src_path.name}")
        pages = extract_pages(src_path)
        print(f"          -> {len(pages)} pages of text")

        chunks = chunk_pages(pages, source=src_path.name, sport=src.sport)
        print(f"[chunk ]  {src.sport}: {len(chunks)} chunks "
              f"(avg {sum(len(c.text) for c in chunks) // max(len(chunks), 1)} chars)")

        all_chunks.extend(chunks)

    gold_chunks = load_gold_chunks(repo_root / GOLD_LOG)
    if gold_chunks:
        by_sport: dict[str, int] = {}
        for c in gold_chunks:
            by_sport[c.sport] = by_sport.get(c.sport, 0) + 1
        print(f"[gold  ]  {len(gold_chunks)} chunks from user-authored gold answers "
              f"({', '.join(f'{s}={n}' for s, n in sorted(by_sport.items()))})")
        all_chunks.extend(gold_chunks)

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
