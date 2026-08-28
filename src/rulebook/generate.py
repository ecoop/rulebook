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
from .registry import display_labels
from .retrieve import RetrievedChunk

SYSTEM_PROMPT_TEMPLATE = """You are an assistant that answers questions about the rules of {domains_phrase} using ONLY the excerpts provided in the <context> block.

Rules for your answer:
- Cite the source of every specific claim inline, in the form [domain rule_id], using the domain and rule id from the context block that supports it. Example: [ultimate II.B.1].
- If the context does not contain the answer, say so plainly. Do NOT fill in from general knowledge.
- Only the rule sets named above are available. If the question mentions any other game or domain (one with no excerpt in the context block), do NOT supply its rules from general knowledge or invent a [domain rule_id] for it — say plainly that its rules aren't in the provided context. You MAY still relay what an available rule set's own excerpts say about that other game, cited to the available domain.
- For questions that compare two domains, structure your answer by domain so the differences are obvious. If one domain's context doesn't address the topic, say that too.
- Be concise. One or two short paragraphs is usually enough."""


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
    return SYSTEM_PROMPT_TEMPLATE.format(domains_phrase=phrase)

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
    retrieved chunk has the same domain AND rule_id. Catches both a real domain
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
        domain = m.group(1)
        # Drop a trailing page suffix the model may copy from the context header
        # (" — p.3" / " — pp.3-4"); citations key on the bare rule_id.
        rule_id = m.group(2).strip().split(" — ")[0].strip()
        label = f"{domain} {rule_id}"
        if (domain, rule_id) not in valid and label not in flagged:
            flagged.append(label)
    return flagged


def generate_answer(question: str, chunks: list[RetrievedChunk]) -> GeneratedAnswer:
    """Call Claude with the retrieved chunks and return the answer + usage.

    The call goes through llm-cost-governor's ``guarded_call`` so cost caps
    and the event log fire uniformly. ``raise_on_truncation=False``
    keeps our existing behavior of returning the truncated text and
    surfacing ``stop_reason`` to the UI instead of raising.
    """
    client = Anthropic(api_key=settings.anthropic_api_key)
    context = format_context(chunks)
    # Distinct domains present in the retrieved context, in first-seen order,
    # named by their registry display name (#113) — "Ultimate (USAU)", not the
    # bare slug. Citations still key on the slug shown in each context header.
    domains = list(dict.fromkeys(c.domain for c in chunks))
    labels = display_labels(domains)
    system_prompt = build_system_prompt([labels[d] for d in domains])
    hooks = [
        # Fail closed on a model lcg can't price ($0 → invisible spend → the
        # WindowedCapHook below never trips). Ordered first so it gates the call.
        RequirePricedModelHook(),
        WindowedCapHook(app_state.cost_counter, identity_provider=app_state.current_guest_token),
        app_state.provider_totals_hook,
        EventLogHook(enabled=settings.guardrails_enabled),
    ]
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
                "content": USER_TEMPLATE.format(context=context, question=question),
            }
        ],
    )
    text = "".join(block.text for block in resp.content if getattr(block, "type", None) == "text")
    return GeneratedAnswer(
        answer=text,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
        stop_reason=resp.stop_reason or "",
    )
