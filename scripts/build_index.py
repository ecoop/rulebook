"""Build the RAG index from the rulesets under ./rules/ (one index per slug).

Run:
    uv run python scripts/build_index.py

Sources are discovered by ``rulebook.rulesets``: a folder of rule files
(``.pdf``/``.md``/``.txt``) is a ruleset; a folder of folders is a game whose
subfolders are editions. Each ruleset's slug comes from its machine-written
``.ruleset.json`` marker, written on the first build from the path
(``rules/tennis/`` -> ``tennis``, ``rules/ultimate/1990/`` -> ``ultimate_1990``).
Add a ruleset by dropping a folder of files in; no code change needed.

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
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path

from tqdm import tqdm

from rulebook import app_state
from rulebook.chunking import Chunk, chunk_pages
from rulebook.config import settings
from rulebook.embeddings import get_embedder
from rulebook.gold_domains import DOMAIN_HEADING, qa_domains, resolve_domains
from rulebook.ingest import extract_pages
from rulebook.interaction_log import (
    log_index_build,
    read_latest_curation,
    read_latest_source_curation,
    read_qa_entries,
)
from rulebook.rulesets import discover, ensure_markers, file_sha256
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


# Root of the source tree; see rulebook.rulesets for the layout rules.
RULES_ROOT = Path("rules")


def discover_sources(
    rules_root: Path,
    *,
    apply_curation: bool = True,
    report: bool = False,
    write_markers: bool = False,
    known_hashes: dict[str, set[str]] | None = None,
) -> list[Source]:
    """Return one Source per ingestable file, tagged with its ruleset's slug.

    Layout (rulebook.rulesets has the full rules):
        rules/
            tennis/          -> flat ruleset, domain="tennis"
            ultimate/        -> a game holding only edition folders
                1990/        -> domain from its .ruleset.json marker, else "ultimate_1990"
                2026/        -> ditto (e.g. "ultimate", kept from when it was flat)

    A folder with both rule files and edition folders builds its own files and
    reports the edition folders (not built). Problems are printed when
    ``report`` is set (the CLI build); the API's read-only listings stay quiet.

    ``write_markers`` writes each ruleset's marker if missing (only the build
    does this). ``known_hashes`` ({slug: sha256s} from the built manifests)
    turns on duplicate and moved-folder checks.

    Skip rule: if a ``<stem>.pdf`` and ``<stem>.extracted.md`` are
    siblings, the PDF is skipped in favor of the extracted markdown.
    That's the pattern for image-only PDFs where pypdf produces nothing
    and vision_extract.py has already cached a proper text transcription
    next to the original.

    Admin curation: if ``apply_curation`` is True (the default), files
    whose latest source_curation row set included=False are dropped.
    Absent from the log = included by default, so freshly-added files
    flow into the index automatically. The admin UI (GET /advanced/sources)
    passes apply_curation=False so it can show both included and
    excluded files. Curation keys are paths (``rules/<game>/<edition>/<file>``
    when nested), so moving a file resets its curation to included.
    """
    excluded_paths: set[str] = set()
    if apply_curation:
        excluded_paths = {
            path for path, included in read_latest_source_curation().items()
            if not included
        }

    found = discover(rules_root, hash_files=report, known_hashes=known_hashes)
    if report:
        for issue in found.issues:
            print(f"[{issue.level:<6}]  {issue.path}: {issue.message}")
    if write_markers:
        for path in ensure_markers(found):
            print(f"[marker]  wrote {path}")

    sources: list[Source] = []
    dropped_by_curation = 0
    for rs in found.rulesets:
        for f in rs.files:
            rel = f.relative_to(rules_root.parent).as_posix()
            if rel in excluded_paths:
                dropped_by_curation += 1
                continue
            sources.append(Source(domain=rs.slug, path=f))

    if dropped_by_curation:
        print(f"[curate]  {dropped_by_curation} source file(s) excluded by admin")
    return sources


def known_source_hashes(index_root: Path) -> dict[str, set[str]]:
    """{slug: sha256s} recorded in each built index's provenance (empty for
    indexes built before hashes were recorded)."""
    from rulebook.store import domain_index_path, list_domains, read_manifest

    out: dict[str, set[str]] = {}
    for slug in list_domains(index_root):
        srcs = read_manifest(domain_index_path(index_root, slug)).get("sources") or []
        out[slug] = {s["sha256"] for s in srcs if isinstance(s, dict) and s.get("sha256")}
    return out

# Embed in batches so we play nice with the embedder's request-size limits
# and get a useful progress bar. Voyage caps requests at 1000 items or
# ~120k tokens per call; 64 is well under both for our chunk sizes.
EMBED_BATCH_SIZE = 64


def load_gold_chunks(gold_path: Path, known_domains: set[str]) -> tuple[list[Chunk], list[dict]]:
    """Turn user-authored gold answers into per-domain retrievable chunks.

    Gold answers are append-only in gold.jsonl (latest row per gold_id wins).
    Each gold is split on ``## Domain`` headings into per-domain section chunks;
    its cross-domain "shared" text (preamble + non-domain headings) fans into the
    covered domains (#133). A heading-less gold indexes into the domains it NAMES
    (#135) — its persisted ``domains``, else the originating question's frozen
    qa_log list, else the legacy set — NOT every domain.
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
    # qa_log rows by qa_id — the frozen domain list a heading-less gold's
    # question ran against (#135), so it indexes only where it belongs.
    qa_index = {r["qa_id"]: r for r in read_qa_entries()}
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
            # No `## Domain` sections — index the whole gold into the domains it
            # NAMES (#135): its persisted `domains`, else the qa_log's frozen
            # list, else the legacy set — never today's live "all". Toggle off to
            # restore the pre-#135 fan-to-every-domain behavior.
            if settings.gold_domain_attribution:
                qrow = qa_index.get(row.get("qa_id"))
                target = resolve_domains(
                    explicit=row.get("domains"),
                    qa=qa_domains(qrow) if qrow else None,
                    legacy=settings.gold_legacy_domains,
                    known=known,
                )
            else:
                target = sorted(known)
            gold_domains = sorted(target)
            for domain in target:
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
    matches = list(DOMAIN_HEADING.finditer(text))
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
    rules_root: Path,
    meta: tuple[str | None, str | None],
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
        c = chunk_pages(
            pages,
            source=src.path.name,
            domain=domain,
            section_headers=settings.chunk_section_headers,
        )
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
        # Content hashes: the next build uses them to warn about duplicate files
        # and to recognize this ruleset's folder if it moves without its marker.
        "sources": [
            {
                "domain": domain,
                "file": s.path.name,
                "path": s.path.relative_to(rules_root).as_posix(),
                "sha256": file_sha256(s.path),
            }
            for s in sources
        ],
        "game": meta[0],
        "edition": meta[1],
        "gold_answers": len(dom_records),
        "gold_chunks": len(dom_golds),
        "golds": dom_records,
        "chunks_by_domain": {domain: len(chunks)},
        "section_headers": settings.chunk_section_headers,
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

    sources = discover_sources(
        rules_root,
        report=True,
        write_markers=True,
        known_hashes=known_source_hashes(settings.resolved_index_path),
    )
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
                f"--domain {args.domain!r} matches no ruleset under {rules_root}; "
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

    from rulebook.rulesets import ruleset_meta

    meta = ruleset_meta(rules_root)
    embedder = get_embedder()
    total = 0
    for domain in targets:
        dom_sources = [s for s in sources if s.domain == domain]
        total += _build_domain(
            domain, dom_sources, rules_root, meta.get(domain, (None, None)),
            gold_chunks, gold_records, embedder,
        )

    print(f"[done  ]  built {len(targets)} domain(s), {total} total rows "
          f"→ {settings.resolved_index_path}/<domain>/")
    if not args.domain:
        report_unbuilt_indexes(settings.resolved_index_path, targets)


def report_unbuilt_indexes(index_root: Path, built: list[str]) -> list[str]:
    """After a full build, name each index that no ruleset folder built this time.

    That's a ruleset held back above (two folders claiming one slug, a folder moved
    without its marker) or one whose folder is gone. Its last index stays on disk
    and is still served; nothing is deleted. Returns the slugs reported.
    """
    from rulebook.store import domain_index_path, list_domains, read_manifest

    kept = sorted(set(list_domains(index_root)) - set(built))
    for slug in kept:
        path = domain_index_path(index_root, slug)
        build = read_manifest(path).get("build_id", "unknown")
        print(f"[keep  ]  {slug}: not built this time; its last index (build {build}) is still "
              f"served. Fix its folder (see above), or remove {path} if the ruleset is gone.")
    return kept


if __name__ == "__main__":
    main()
