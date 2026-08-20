"""Build the RAG index from the source files under ./rules/<domain>/.

Run:
    uv run python scripts/build_index.py

Sources are discovered by walking ``rules/<domain>/`` — the parent
directory name is the domain tag. Every ``.pdf``, ``.md``, and ``.txt``
in there is ingested. Add a new domain by creating a new sibling
directory; add a new resource by dropping a file into the domain's dir.
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
from datetime import UTC
from pathlib import Path

from tqdm import tqdm

from rulebook import app_state
from rulebook.chunking import Chunk, chunk_pages
from rulebook.config import settings
from rulebook.embeddings import get_embedder
from rulebook.ingest import extract_pages
from rulebook.interaction_log import (
    log_index_build,
    read_latest_curation,
    read_latest_source_curation,
)
from rulebook.store import domain_index_path, write_store

# Guardrails singletons — needed so the embedding calls this script
# makes can record_usage against the cost counter. Same initialize()
# the API server calls.
app_state.initialize(settings)


@dataclass
class Source:
    domain: str
    # PDF (born-digital) or a Markdown/text file (e.g. output from
    # scripts/vision_extract.py for image-only PDFs). Both are handled
    # transparently by ingest.extract_pages.
    path: Path


# Root of the source tree; each immediate subdirectory is one domain.
RULES_ROOT = Path("rules")

# File suffixes we treat as ingestable sources.
_SOURCE_SUFFIXES = {".pdf", ".md", ".txt"}


def discover_sources(rules_root: Path, *, apply_curation: bool = True) -> list[Source]:
    """Walk ``rules/<domain>/`` and return one Source per ingestable file.

    Convention:
        rules/
            ultimate/       -> domain="ultimate", every .pdf/.md/.txt inside
            goaltimate/     -> domain="goaltimate", ditto

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
    for domain_dir in sorted(p for p in rules_root.iterdir() if p.is_dir()):
        domain = domain_dir.name
        # Build the set of stems that have an .extracted.md so we can
        # skip their .pdf siblings in this dir.
        extracted_stems = {
            p.name.removesuffix(".extracted.md")
            for p in domain_dir.iterdir()
            if p.name.endswith(".extracted.md")
        }
        for f in sorted(domain_dir.iterdir()):
            if not f.is_file() or f.suffix.lower() not in _SOURCE_SUFFIXES:
                continue
            if f.suffix.lower() == ".pdf" and f.stem in extracted_stems:
                # Skip — the .extracted.md sibling is the ingestable form.
                continue
            rel = f.relative_to(rules_root.parent).as_posix()
            if rel in excluded_paths:
                dropped_by_curation += 1
                continue
            sources.append(Source(domain=domain, path=f))

    if dropped_by_curation:
        print(f"[curate]  {dropped_by_curation} source file(s) excluded by admin")
    return sources

# Embed in batches so we play nice with the embedder's request-size limits
# and get a useful progress bar. Voyage caps requests at 1000 items or
# ~120k tokens per call; 64 is well under both for our chunk sizes.
EMBED_BATCH_SIZE = 64


# Section-heading pattern for splitting a gold answer into per-domain
# chunks. Matches a line beginning with "## Ultimate" or "## Goaltimate"
# (case-insensitive). If a gold answer has no such headings, the whole
# text becomes one chunk tagged with every known domain (so it retrieves
# for any domain-filtered query).
_DOMAIN_HEADING = re.compile(r"^\s*##\s+([A-Za-z][A-Za-z_ -]*?)\s*$", re.M)


def load_gold_chunks(gold_path: Path, known_domains: set[str]) -> tuple[list[Chunk], list[dict]]:
    """Turn user-authored gold answers into per-domain retrievable chunks.

    Gold answers are append-only in gold.jsonl (latest row per qa_id
    wins). Each surviving gold is split on ``## Domain`` headings; each
    section becomes one Chunk tagged with that domain. Sections whose
    heading isn't a recognized domain are ignored. A gold answer with no
    matching headings falls back to one shared chunk per known domain so
    the content still retrieves under any domain filter.

    Chunk metadata is chosen so citations read clearly downstream:
        rule_id = f"user-gold-{qa_id[:8]}"
        source  = "gold.jsonl"
        page    = 0 (no meaningful page for user text)
    """
    if not gold_path.exists():
        return [], []

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

    known = set(known_domains)
    chunks: list[Chunk] = []
    records: list[dict] = []  # one per contributing gold, for build provenance
    for row in latest.values():
        text = row["gold_answer"].strip()
        if not text:
            continue

        domain_sections, shared = _split_gold_sections(text, known)

        def _gold_chunk(domain: str, body: str) -> Chunk:
            return Chunk(
                source="gold.jsonl", domain=domain, rule_id="correction",
                page_start=0, page_end=0, text=body,
            )

        if not domain_sections:
            # No known-domain sections — index the whole gold once per domain so
            # a general answer is retrievable under any domain filter.
            gold_domains = sorted(known)
            for domain in known:
                chunks.append(_gold_chunk(domain, text))
        else:
            # Domain sections → one chunk each. The gold's cross-domain "shared"
            # text (preamble + non-domain headings) fans into every domain the
            # gold COVERS (#133), so it retrieves alongside the specific chunk;
            # gated by settings.gold_shared_fanout.
            gold_domains = sorted({d for d, _ in domain_sections})
            for domain, section_text in domain_sections:
                chunks.append(_gold_chunk(domain, section_text))
            if shared and settings.gold_shared_fanout:
                for domain in gold_domains:
                    chunks.append(_gold_chunk(domain, shared))

        records.append({
            "gold_id": row.get("gold_id"),
            "author": row.get("author"),
            "question": row.get("question", ""),
            "domains": gold_domains,
        })
    return chunks, records


def _split_gold_sections(
    text: str, known_domains: set[str]
) -> tuple[list[tuple[str, str]], str]:
    """Split a gold into ([(domain, section_text)], shared_text).

    Each ``## <known-domain>`` heading yields one domain section. The **shared**
    text is everything cross-domain: the leading preamble (before the first
    heading) plus any section under a NON-domain heading (``## Shared`` /
    ``## General`` / …). Callers fan the shared text into the gold's covered
    domains (#133) instead of dropping it. Returns ``([], "")`` when there are no
    ``##`` headings at all — the caller handles that heading-less fan-out.
    """
    matches = list(_DOMAIN_HEADING.finditer(text))
    if not matches:
        return [], ""

    domain_sections: list[tuple[str, str]] = []
    shared_parts: list[str] = []
    preamble = text[: matches[0].start()].strip()
    if preamble:
        shared_parts.append(preamble)

    for i, m in enumerate(matches):
        name = m.group(1).strip().lower()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section_text = text[start:end].strip()
        if not section_text:
            continue
        if name in known_domains:
            domain_sections.append((name, section_text))
        else:
            shared_parts.append(section_text)  # non-domain heading → shared

    return domain_sections, "\n\n".join(shared_parts)


def _build_domain(
    domain: str,
    sources: list[Source],
    gold_chunks: list[Chunk],
    gold_records: list[dict],
    embedder,
) -> int:
    """Chunk + embed + write + publish ONE domain's index (#128). Rows written."""
    from datetime import datetime

    from rulebook.build_info import BUILD_INFO
    from rulebook.index_sync import publish_index_to_gcs

    chunks: list[Chunk] = []
    for src in sources:
        print(f"[ingest]  {domain}: reading {src.path.name}")
        pages = extract_pages(src.path)
        print(f"          -> {len(pages)} pages of text")
        c = chunk_pages(pages, source=src.path.name, domain=domain)
        print(f"[chunk ]  {domain}: {len(c)} chunks "
              f"(avg {sum(len(x.text) for x in c) // max(len(c), 1)} chars)")
        chunks.extend(c)

    dom_golds = [c for c in gold_chunks if c.domain == domain]
    if dom_golds:
        print(f"[gold  ]  {domain}: {len(dom_golds)} chunks from user-authored golds")
        chunks.extend(dom_golds)

    if not chunks:
        print(f"[skip  ]  {domain}: no chunks produced — skipping")
        return 0

    print(f"[embed ]  {domain}: {len(chunks)} chunks via "
          f"{settings.embedding_provider}/{settings.embedding_model}")
    vectors: list[list[float]] = []
    for i in tqdm(range(0, len(chunks), EMBED_BATCH_SIZE), desc=f"  {domain}"):
        batch = chunks[i : i + EMBED_BATCH_SIZE]
        vectors.extend(embedder.embed([c.text for c in batch], input_type="document"))

    now = datetime.now(UTC)
    dom_records = [r for r in gold_records if domain in r.get("domains", [])]
    provenance = {
        "build_id": now.strftime("%Y%m%dT%H%M%SZ"),
        "built_at": now.isoformat(timespec="seconds"),
        "git_sha": BUILD_INFO.sha,
        "build_num": BUILD_INFO.build_num,
        "domain": domain,
        "sources": [{"domain": domain, "file": s.path.name} for s in sources],
        "gold_answers": len(dom_records),
        "gold_chunks": len(dom_golds),
        "golds": dom_records,
        "chunks_by_domain": {domain: len(chunks)},
    }
    written = write_store(
        domain_index_path(settings.resolved_index_path, domain),
        chunks,
        vectors,
        provider=settings.embedding_provider,
        model=settings.embedding_model,
        manifest_extra=provenance,
    )
    print(f"[store ]  {domain}: wrote {written} rows "
          f"(build {provenance['build_id']} @ {provenance['git_sha']})")

    # Durable per-domain build history (Indices tab). Self-contained manifest.
    log_index_build({
        **provenance,
        "provider": settings.embedding_provider,
        "model": settings.embedding_model,
        "count": written,
        "dimension": len(vectors[0]) if vectors else 0,
        "domains": [domain],
    })

    # On a hosted (gcs) deploy, push just this domain's index to the bucket so
    # the rebuild is durable (otherwise it lives only in this instance's /tmp).
    if publish_index_to_gcs(domain):
        print(f"[publish]  {domain}: uploaded to "
              f"gs://{settings.gcs_state_bucket}/index/{domain}/")
    return written


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Build the per-domain RAG index (#128).")
    parser.add_argument(
        "--domain",
        help="build only this domain's index (default: rebuild every discovered domain)",
    )
    args = parser.parse_args(argv)

    # Use settings.rules_dir, not repo_root / RULES_ROOT: once rulebook is
    # pip-installed, repo_root resolves to a site-packages ancestor with no
    # rules/. rules_dir has the fallback the running app already relies on
    # (CWD-relative rules/, i.e. /app/rules when we run with cwd=/app).
    rules_root = settings.rules_dir
    if not rules_root.is_dir():
        raise FileNotFoundError(f"Missing rules directory: {rules_root}")

    sources = discover_sources(rules_root)
    if not sources:
        raise RuntimeError(
            f"No source files found under {rules_root}. Add PDFs or .md files"
            " to rules/<domain>/ and re-run."
        )
    all_domains = sorted({s.domain for s in sources})
    print(f"[found ]  {len(sources)} source files across "
          f"{len(all_domains)} domain(s): {', '.join(all_domains)}")

    if args.domain:
        if args.domain not in all_domains:
            raise SystemExit(
                f"--domain {args.domain!r} has no rules/{args.domain}/ sources; "
                f"one of {all_domains}"
            )
        targets = [args.domain]
    else:
        targets = all_domains
        # Full rebuild: drop any pre-#128 flat index files at the root so the
        # only thing left is the per-domain subdirs.
        from rulebook.store import CHUNKS_FILE, MANIFEST_FILE, VECTORS_FILE
        for name in (VECTORS_FILE, CHUNKS_FILE, MANIFEST_FILE):
            (settings.resolved_index_path / name).unlink(missing_ok=True)

    # Load golds ONCE against ALL known domains, so a targeted build still
    # routes '## <Domain>' golds correctly and heading-less golds fan out fully.
    gold_chunks, gold_records = load_gold_chunks(
        settings.data_dir / "logs" / "gold.jsonl", set(all_domains)
    )

    embedder = get_embedder()
    total = 0
    for domain in targets:
        dom_sources = [s for s in sources if s.domain == domain]
        total += _build_domain(domain, dom_sources, gold_chunks, gold_records, embedder)

    print(f"[done  ]  built {len(targets)} domain(s), {total} total rows "
          f"→ {settings.resolved_index_path}/<domain>/")


if __name__ == "__main__":
    main()
