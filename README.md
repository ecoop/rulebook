# Rulebook

_Last updated: 2026-08-27_

A RAG (retrieval-augmented generation) app that answers questions about the rules of games, across several **domains**: the disc sports **ultimate** and **goaltimate**, plus **badminton**, **curling**, **hearts**, and **backgammon**. Ask a question, get an answer with citations back to the specific rule, and see the retrieved passages that produced it.

It started as a hands-on way to **learn RAG** and has grown into a small gated product: per-user invite auth, capability-based roles (RBAC), a human-in-the-loop review loop (rate answers, author "gold" answers, curate sources, rebuild the index), and cost governance. Each pipeline stage still lives in its own small, commented module.

> New here? The in-app **"How it works"** panel walks the live pipeline. Deeper topics have their own docs — see [Documentation](#documentation).

## What's in here

```
rulebook/
├── rules/<domain>/            # source rule docs, one dir per domain (slug = dir name);
│                              #   discovery is data-driven — add a domain by adding a dir
├── data/index/<domain>/       # local vector index per domain (built by build_index.py)
├── src/rulebook/
│   ├── config.py              # env/config + model selection
│   ├── ingest.py              # PDF → text with page numbers (Claude vision for image pages)
│   ├── chunking.py            # rule-number / heading-aware chunker
│   ├── embeddings.py          # pluggable Voyage / OpenAI embeddings
│   ├── store.py               # in-memory numpy vector store (.npy matrix + .jsonl records)
│   ├── retrieve.py            # single-domain and cross-domain retrieval
│   ├── generate.py            # Claude call with a citation-forcing prompt
│   ├── pipeline.py            # end-to-end: question → answer + citations
│   ├── roles.py               # capability-based RBAC (level0–8, ROLE_CAPABILITIES)
│   ├── allowed_domains.py     # per-user domain scoping
│   ├── registry.py            # per-domain metadata (display name, source URLs)
│   ├── interaction_log.py     # append-only JSONL logs (qa / feedback / gold)
│   └── {index,log,rules}_sync.py  # sync index / logs / rule docs with GCS (hosted)
├── scripts/build_index.py     # ingest every rules/<domain>/ → the vector index
├── api/main.py                # FastAPI: /ask, /meta, /me, /feedback, /gold, /advanced/*
├── web/                       # Vite + React + Tailwind (Ask + "Your activity")
└── docs/                      # deploy, RBAC, roles, sources… (see Documentation)
```

## How it works, briefly

1. **Ingest** — pull text from each rule doc, keeping page numbers; image-only pages are transcribed by Claude vision.
2. **Chunk** — split on rule numbering / headings so citations map to real rules, not mid-clause fragments.
3. **Embed** — each chunk → a vector via Voyage AI.
4. **Store** — vectors + metadata in `data/index/<domain>/` (a `.npy` matrix + a `.jsonl` of chunk records). At query time it all loads into memory; for this corpus a numpy dot product *is* the vector search.
5. **Retrieve** — embed the question, pull top-_k_ nearest chunks; for cross-domain questions, top-_k_ per domain.
6. **Generate** — Claude answers using only the retrieved chunks, forced to cite each claim as `[domain rule_id]` and to refuse rules not in context.

The `/ask` response returns the retrieved chunks alongside the answer, so the UI shows exactly what the model was given.

## Setup (local)

You need [uv](https://docs.astral.sh/uv/).

```bash
uv sync                 # install deps into .venv
cp .env.example .env    # then add your keys
```

Keys:

- `ANTHROPIC_API_KEY` — generation (billed per token; Claude Max does **not** cover API use). Pennies per session.
- `VOYAGE_API_KEY` — embeddings ([voyageai.com](https://www.voyageai.com/)); swap to OpenAI with `EMBEDDING_PROVIDER=openai` + `OPENAI_API_KEY`.

Build the index and run:

```bash
uv run python scripts/build_index.py     # ingest rules/<domain>/ → data/index/
uv run uvicorn api.main:app --reload     # API on :8000
cd web && npm install && npm run dev     # frontend on :5173
```

`build_index.py` discovers domains from the `rules/` subdirectories — no code change to add one.

## Adding a domain

1. Create `rules/<slug>/` and drop the rule doc(s) in (see [`rules/SOURCES.md`](rules/SOURCES.md) for the source/copyright policy — copyrighted docs stay untracked).
2. `uv run python scripts/build_index.py` (discovery picks up the new dir).
3. Register display name + source URL(s): `uv run python -m scripts.domains set <slug> --name "…" --sources <url>`.
4. Grant access (hosted): new domains reach no one until granted (per-user allowlist).

Nothing in retrieval or generation is domain-specific — they read the `domain` off each chunk.

## Hosted / gated demo

Rulebook runs as an invite-only demo, using the [`guest-auth`](https://github.com/ecoop/guest-auth) library.

- **Local / simple:** `RULEBOOK_DEMO_MODE=true` and inline tokens via `RULEBOOK_INVITE_TOKENS='{"tok_…":"label"}'`.
- **Hosted:** tokens + roles + domain grants live in a GCS state bucket (not env), managed **live** from the **Users** tab — add/suspend/remove invitees and change roles without a redeploy. Roles are capability-based (level0 suspended … level8 superuser); see [`docs/roles.md`](docs/roles.md) and [`docs/rbac-capabilities.md`](docs/rbac-capabilities.md).

Deploy is a single `./scripts/deploy.sh` to the `rulebook-prod` Cloud Run project; see [`docs/migrate-to-rulebook-prod.md`](docs/migrate-to-rulebook-prod.md) for the project layout.

## Human-in-the-loop

By capability, signed-in users rate answers, tag issues, comment, and author "gold" answers; curators include/exclude sources and rebuild the index. That feedback is logged and folds back into retrieval and a gold-answer corpus. The **"Your activity"** view surfaces questions, feedback, golds, sources, users, and index builds.

## Documentation

- [`docs/roles.md`](docs/roles.md), [`docs/rbac-capabilities.md`](docs/rbac-capabilities.md) — the RBAC model (roles, capabilities, domain scoping).
- [`docs/users-tab.md`](docs/users-tab.md) — managing invitees.
- [`docs/migrate-to-rulebook-prod.md`](docs/migrate-to-rulebook-prod.md) — hosting / project layout.
- [`rules/SOURCES.md`](rules/SOURCES.md) — where each domain's rules come from + the copyright policy.

## Not done (yet)

Reranking (baseline top-_k_ only), hybrid/BM25 retrieval, streaming answers, and an automated eval harness — each left as a clear next step.

## License

MIT — see [LICENSE](LICENSE). This covers the **code** only. The rule documents
each domain is built from are third-party works published by their governing
bodies (see [`rules/SOURCES.md`](rules/SOURCES.md)); they are not included in this
repository, nor licensed by this project.
