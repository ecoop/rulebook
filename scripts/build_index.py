"""Build the RAG index from the source files under ./rules/<sport>/.

Run:
    uv run python scripts/build_index.py

Sources are discovered by walking ``rules/<sport>/`` — the parent
directory name is the sport tag. Every ``.pdf``, ``.md``, and ``.txt``
in there is ingested. Add a new sport by creating a new sibling
directory; add a new resource by dropping a file into the sport's dir.
No code change needed.

Pipeline per source:
    file -> ingest.extract_pages -> chunking.chunk_pages
        -> embeddings.embed(input_type="document")
        -> store.write_store

Idempotent: rewrites the index from scratch every time. That's the safe
default when your chunking or embedding model might change — a partial
rebuild would leave old vectors in an inconsistent state next to the new
ones and retrieval quality would silently degrade.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from tqdm import tqdm

from rulebook import app_state
from rulebook.chunking import Chunk, chunk_pages
from rulebook.config import settings
from rulebook.embeddings import get_embedder
from rulebook.ingest import extract_pages
from rulebook.interaction_log import read_latest_curation, read_latest_source_curation
from rulebook.pipeline import DEFAULT_SPORTS
from rulebook.store import write_store

# Guardrails singletons — needed so the embedding calls this script
# makes can record_usage against the cost counter. Same initialize()
# the API server calls.
app_state.initialize(settings)


@dataclass
class Source:
    sport: str
    # PDF (born-digital) or a Markdown/text file (e.g. output from
    # scripts/vision_extract.py for image-only PDFs). Both are handled
    # transparently by ingest.extract_pages.
    path: Path


# Root of the source tree; each immediate subdirectory is one sport.
RULES_ROOT = Path("rules")

# File suffixes we treat as ingestable sources.
_SOURCE_SUFFIXES = {".pdf", ".md", ".txt"}


def discover_sources(rules_root: Path, *, apply_curation: bool = True) -> list[Source]:
    """Walk ``rules/<sport>/`` and return one Source per ingestable file.

    Convention:
        rules/
            ultimate/       -> sport="ultimate", every .pdf/.md/.txt inside
            goaltimate/     -> sport="goaltimate", ditto

    Skip rule: if a ``<stem>.pdf`` and ``<stem>.extracted.md`` are
    siblings, the PDF is skipped in favor of the extracted markdown.
    That's the pattern for image-only PDFs where pypdf produces nothing
    and vision_extract.py has already cached a proper text transcription
    next to the original.

    Admin curation: if ``apply_curation`` is True (the default), files
    whose latest source_curation row set included=False are dropped.
    Absent from the log = included by default, so freshly-added files
    flow into the index automatically. The admin UI (GET /admin/sources)
    passes apply_curation=False so it can show both included and
    excluded files.
    """
    excluded_paths: set[str] = set()
    if apply_curation:
        excluded_paths = {
            path for path, included in read_latest_source_curation().items()
            if not included
        }

    sources: list[Source] = []
    dropped_by_curation = 0
    for sport_dir in sorted(p for p in rules_root.iterdir() if p.is_dir()):
        sport = sport_dir.name
        # Build the set of stems that have an .extracted.md so we can
        # skip their .pdf siblings in this dir.
        extracted_stems = {
            p.name.removesuffix(".extracted.md")
            for p in sport_dir.iterdir()
            if p.name.endswith(".extracted.md")
        }
        for f in sorted(sport_dir.iterdir()):
            if not f.is_file() or f.suffix.lower() not in _SOURCE_SUFFIXES:
                continue
            if f.suffix.lower() == ".pdf" and f.stem in extracted_stems:
                # Skip — the .extracted.md sibling is the ingestable form.
                continue
            rel = f.relative_to(rules_root.parent).as_posix()
            if rel in excluded_paths:
                dropped_by_curation += 1
                continue
            sources.append(Source(sport=sport, path=f))

    if dropped_by_curation:
        print(f"[curate]  {dropped_by_curation} source file(s) excluded by admin")
    return sources

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

    # Latest row per gold_id wins — walk the file and keep last-write-wins.
    # Golds are owned entities now, so several can share a qa_id; legacy rows
    # (no gold_id) fall back to their qa_id as the id (matches legacy curation).
    latest: dict[str, dict] = {}
    with gold_path.open() as f:
        for line in f:
            row = json.loads(line)
            row["gold_id"] = row.get("gold_id") or row["qa_id"]
            latest[row["gold_id"]] = row

    # Apply admin curation: skip golds whose latest curation row set
    # included=False. Absent from the curation log = included by default,
    # so freshly-authored golds flow into the index automatically.
    curation = read_latest_curation()
    excluded = {gid for gid, included in curation.items() if not included}
    if excluded:
        latest = {gid: row for gid, row in latest.items() if gid not in excluded}
        print(f"[curate]  {len(excluded)} gold(s) excluded by admin")

    known = set(DEFAULT_SPORTS)
    chunks: list[Chunk] = []
    for row in latest.values():
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
                        rule_id="correction",
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
                    rule_id="correction",
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

    rules_root = repo_root / RULES_ROOT
    if not rules_root.is_dir():
        raise FileNotFoundError(f"Missing rules directory: {rules_root}")

    sources = discover_sources(rules_root)
    if not sources:
        raise RuntimeError(
            f"No source files found under {rules_root}. Add PDFs or .md files"
            " to rules/<sport>/ and re-run."
        )
    print(f"[found ]  {len(sources)} source files across {len({s.sport for s in sources})} sport(s)")

    all_chunks: list[Chunk] = []
    for src in sources:
        print(f"[ingest]  {src.sport}: reading {src.path.name}")
        pages = extract_pages(src.path)
        print(f"          -> {len(pages)} pages of text")

        chunks = chunk_pages(pages, source=src.path.name, sport=src.sport)
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
