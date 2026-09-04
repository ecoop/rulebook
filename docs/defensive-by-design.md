<!-- Copyright (c) 2026 Eric Cooper. -->
# Defensive by design

_Last updated: 2026-09-02_

Rulebook treats every LLM call as **costly and not to be trusted blindly**, and
guards it at the boundary. The defenses fall into four areas, each backed by code.

## Cost containment (fail-closed, layered)

Every Claude and embedding call is metered and capped, and the app refuses to run
misconfigured:

- **Boot guards.** `_assert_models_priceable` refuses to start if a configured
  model prices at $0 in llm-cost-governor — an unpriced model bills $0, so the
  spend caps would silently under-enforce. `_assert_model_roles` asserts the chat
  model is a chat model and the embedding model an embedding model, so a swapped
  config fails at boot instead of mid-request. (`src/rulebook/app_state.py`)
- **Per-call gate.** `RequirePricedModelHook` is prepended to the hook chain on
  every call — generation, embeddings, and vision extraction — so an unpriceable
  model is refused at call time too. (`src/rulebook/generate.py`,
  `src/rulebook/embeddings.py`, `scripts/vision_extract.py`)
- **Rolling caps + rate limit.** `WindowedCapHook` enforces hourly/daily USD
  ceilings with per-guest attribution; a single call over a cap raises. An IP
  rate limit bounds request volume. Every generation routes through
  `guarded_call`; embeddings, which don't fit that wrapper, are metered post-hoc
  via `record_usage` through the same hooks. (`src/rulebook/config.py`,
  `generate.py`, `embeddings.py`)

## Output validation (don't trust the model)

- **Citation grounding.** `find_unverified_citations` checks every
  `[domain rule_id]` the model emits against the chunks actually retrieved, and
  flags hallucinated or out-of-scope citations to the reader. (`generate.py`)
- **Prompt hardening.** The system prompt forces inline citations, forbids
  answering from general knowledge, and refuses to invent rules for a domain
  absent from the retrieved context. (`generate.py`)
- **Retrieval-grounded answers.** Answers are drawn only from retrieved passages.
- **Human-in-the-loop correction.** Users rate answers, tag issues, and author
  "gold" answers; corrections fold back into the index on rebuild.

## Truncation honesty

Generation sets `raise_on_truncation=False` and surfaces `stop_reason` through the
pipeline, API, and UI, so a `max_tokens`-truncated answer is flagged rather than
read as complete. (`generate.py`, `src/rulebook/interaction_log.py`)

## Graceful degradation

The guards degrade rather than crash: if llm-cost-governor's pricing API moves,
the boot checks log and skip instead of failing to start; enforcement is
environment-aware — raise in production, warn-only in local dev — via
`guardrails_enabled`. (`app_state.py`, `config.py`)
