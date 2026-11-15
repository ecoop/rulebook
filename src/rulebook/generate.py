"""Prompt Claude to answer using retrieved chunks, with citations forced.

The generation step is often taken for granted in RAG walkthroughs —
"we just call the LLM with context". In practice the prompt is doing
several things at once:

    1. Frames retrieved chunks as authoritative source material.
    2. Forces citations back to rule ids so the frontend can display them
       and the user can verify claims.
    3. Prevents the model from inventing rules that aren't in context.
       (The classic RAG failure mode: model falls back on general
       training data and hallucinates a rule that sounds plausible.)
    4. Handles "the rulebook doesn't say" gracefully rather than
       pretending it does.

The prompt is deliberately short. Long system prompts are not
automatically better prompts, and each extra instruction is one the
model might overweight. Iterate here when you have real failure modes to
respond to — not in advance.

The default system prompt is a file, prompts/system.md; SYSTEM_PROMPT_FILE
points to your own instead.
"""

import re
from dataclasses import dataclass

from anthropic import Anthropic
from llm_cost_governor.budget import RequirePricedModelHook
from llm_cost_governor.counters import WindowedCapHook
from llm_cost_governor.events import EventLogHook
from llm_cost_governor.wrapper import guarded_call

from . import app_state
from .config import settings
from .ingest import strip_html_comments
from .registry import display_labels
from .retrieve import RetrievedChunk


def system_prompt_template() -> str:
    """The system prompt as written: SYSTEM_PROMPT_FILE, or the default
    prompts/system.md, without its HTML comments. Read on each call, so an edit
    to the file applies to the next question."""
    text = settings.resolved_system_prompt_file.read_text(encoding="utf-8")
    return strip_html_comments(text).strip()


def build_system_prompt(domains: list[str]) -> str:
    """De-hardcoded system prompt (#113): name the actual domains in play.

    The domain set is DATA — derived from the retrieved chunks — not a baked-in
    "disc sports (ultimate, goaltimate)" line, so Rulebook serves any
    cited-answer-over-a-ruleset domain (a legal code, an RPG, policy docs)
    without a prompt edit. Falls back to a generic phrase when we have none.
    """
    if domains:
        phrase = "the following: " + ", ".join(domains)
    else:
        phrase = "the provided rules"
    # replace, not format: a prompt someone writes may contain other braces.
    return system_prompt_template().replace("{domains_phrase}", phrase)

USER_TEMPLATE = """<context>
{context}
</context>

<question>{question}</question>

Answer using only the context above. Cite inline with [domain rule_id]."""


@dataclass
class GeneratedAnswer:
    answer: str
    input_tokens: int
    output_tokens: int
    # Anthropic returns "end_turn" when the model finished naturally,
    # "max_tokens" when we hit the ceiling and cut it off mid-sentence,
    # or other values for tool-use / refusal / etc. Surfaced to the UI
    # so a truncated answer can be flagged instead of read as complete.
    stop_reason: str


def format_context(chunks: list[RetrievedChunk]) -> str:
    """Render retrieved chunks in a shape the model can cite from.

    Each chunk gets a header like:
        [ultimate II.B.1 — pp.12-13]
    which is both the citation format we want back and enough context for
    the model to pick the right chunk to attribute a claim to.

    Gold ("correction") chunks have no meaningful page number — we
    omit the page suffix so the citation reads ``[ultimate correction]``
    rather than the awkward ``[ultimate correction — p.0]``.
    """
    blocks = []
    for c in chunks:
        if c.page_start == 0 and c.page_end == 0:
            header = f"[{c.domain} {c.rule_id}]"
        else:
            pages = (
                f"p.{c.page_start}"
                if c.page_start == c.page_end
                else f"pp.{c.page_start}-{c.page_end}"
            )
            header = f"[{c.domain} {c.rule_id} — {pages}]"
        blocks.append(f"{header}\n{c.text}")
    return "\n\n---\n\n".join(blocks)


# An inline citation the model is told to emit: [<domain-slug> <rule_id>].
# Domain slugs are lowercase; rule_ids may be multi-word ("Object of the Game").
_CITATION_RE = re.compile(r"\[([a-z][a-z0-9_-]*)\s+([^\]]+)\]")


def find_unverified_citations(answer: str, chunks: list[RetrievedChunk]) -> list[str]:
    """Return the answer's [domain rule_id] citations that match no retrieved
    chunk — i.e. passages the model cited but was never given (#172).

    A pure membership check (no LLM call): a citation is verified iff some
    retrieved chunk has the same domain AND either the same rule_id or one it
    sits under. Chunks stop at the section level (``XVII.K.2``) while their
    text carries lettered sub-clauses, so a citation to ``XVII.K.2.a`` or
    ``XVII.K.2(a)`` points inside a passage the model was given. Catches both a real domain
    the caller didn't retrieve (e.g. goaltimate for a user without it) and an
    entirely fabricated one (e.g. poker, not a domain at all). Advisory: callers
    flag, never strip, so a rare non-citation bracket is harmless. Markdown links
    (``[text](url)``) are ignored. Deduped, in first-seen order.
    """
    valid = {(c.domain, c.rule_id.strip()) for c in chunks}
    flagged: list[str] = []
    for m in _CITATION_RE.finditer(answer):
        # Skip markdown links: a `]` immediately followed by `(`.
        if m.end() < len(answer) and answer[m.end()] == "(":
            continue
        for domain, rule_id in _bracket_citations(m.group(1), m.group(2)):
            label = f"{domain} {rule_id}"
            if not _is_covered(domain, rule_id, valid) and label not in flagged:
                flagged.append(label)
    return flagged


_DOMAIN_PREFIX_RE = re.compile(r"([a-z][a-z0-9_-]*)\s+(\S.*)")


def _bracket_citations(domain: str, rest: str) -> list[tuple[str, str]]:
    """The (domain, rule_id) pairs in one bracket.

    Usually one, ``[checkers 4.1]``, but the model sometimes groups several:
    ``[tennis 5.3, tennis 5.4]`` or ``[tennis 5.3; 5.4]``. A later item may name
    its own domain or inherit the bracket's.
    """
    pairs = []
    for i, item in enumerate(re.split(r"\s*[,;]\s*", rest.strip())):
        if i and (m := _DOMAIN_PREFIX_RE.fullmatch(item)):
            item_domain, item = m.group(1), m.group(2)
        else:
            item_domain = domain
        # Drop a trailing page suffix the model may copy from the context header
        # (" — p.3" / " — pp.3-4"); citations key on the bare rule_id.
        rule_id = item.split(" — ")[0].strip()
        if rule_id:
            pairs.append((item_domain, rule_id))
    return pairs


def _is_covered(domain: str, rule_id: str, valid: set[tuple[str, str]]) -> bool:
    """True if ``rule_id`` is a retrieved rule or a sub-clause of one.

    A sub-clause continues its parent's id with ``.`` or ``(`` — so
    ``II.B.1.a`` and ``II.B.1(a)`` fall under ``II.B.1``, but ``II.B.10``
    does not.
    """
    if (domain, rule_id) in valid:
        return True
    return any(
        d == domain and rule_id.startswith(parent) and rule_id[len(parent)] in ".("
        for d, parent in valid
        if len(rule_id) > len(parent)
    )


def build_prompt(question: str, chunks: list[RetrievedChunk]) -> tuple[str, str]:
    """The system prompt and user message Claude is sent for ``question``: no call.

    Separate from :func:`generate_answer` so the exact prompt can be shown (the
    RAG at a glance notebook prints it) without an API key.
    """
    # Distinct domains present in the retrieved context, in first-seen order,
    # named by their registry display name (#113) — "Ultimate (USAU)", not the
    # bare slug. Citations still key on the slug shown in each context header.
    domains = list(dict.fromkeys(c.domain for c in chunks))
    labels = display_labels(domains)
    system_prompt = build_system_prompt([labels[d] for d in domains])
    return system_prompt, USER_TEMPLATE.format(context=format_context(chunks), question=question)


def generate_answer(question: str, chunks: list[RetrievedChunk]) -> GeneratedAnswer:
    """Call Claude with the retrieved chunks and return the answer + usage.

    The call goes through llm-cost-governor's ``guarded_call`` so cost caps
    and the event log fire uniformly. ``raise_on_truncation=False``
    keeps our existing behavior of returning the truncated text and
    surfacing ``stop_reason`` to the UI instead of raising.
    """
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "Generation needs ANTHROPIC_API_KEY, but none is set. Retrieval, indexing, "
            "and eval need no key — only answering does. Add it to your .env (or export "
            "it) to use `ask` or the web app."
        )
    if app_state.cost_counter is None:
        # The cost-cap hook below needs the guardrail singletons; without them it
        # fails deep inside llm-cost-governor with a bare AttributeError.
        raise RuntimeError(
            "Generation runs through the cost guardrails, which aren't set up yet. Call "
            "rulebook.app_state.initialize(settings) first, as api/main.py, rulebook.ask "
            "and notebook.setup() do."
        )
    client = Anthropic(api_key=settings.anthropic_api_key)
    system_prompt, user_message = build_prompt(question, chunks)
    hooks = [
        # Fail closed on a model lcg can't price ($0 → invisible spend → the
        # WindowedCapHook below never trips). Ordered first so it gates the call.
        RequirePricedModelHook(),
        WindowedCapHook(app_state.cost_counter, identity_provider=app_state.current_guest_token),
        app_state.provider_totals_hook,
        EventLogHook(enabled=settings.guardrails_enabled),
    ]
    # Effort only when configured: some models reject output_config.effort.
    extra = {"output_config": {"effort": settings.claude_effort}} if settings.claude_effort else {}
    resp, _usage = guarded_call(
        client,
        provider="anthropic",
        hooks=hooks,
        tags={"stage": "answer"},
        raise_on_truncation=False,
        model=settings.claude_model,
        max_tokens=2048,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": user_message,
            }
        ],
        **extra,
    )
    text = "".join(block.text for block in resp.content if getattr(block, "type", None) == "text")
    return GeneratedAnswer(
        answer=text,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
        stop_reason=resp.stop_reason or "",
    )
