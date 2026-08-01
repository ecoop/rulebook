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

from dataclasses import dataclass

from anthropic import Anthropic
from llm_guardrails.counters import WindowedCapHook
from llm_guardrails.events import EventLogHook
from llm_guardrails.wrapper import guarded_call

from . import app_state
from .config import settings
from .retrieve import RetrievedChunk

SYSTEM_PROMPT = """You are an assistant that answers questions about the rules of disc sports (ultimate, goaltimate) using ONLY the excerpts provided in the <context> block.

Rules for your answer:
- Cite the source of every specific claim inline, in the form [sport rule_id], using the sport and rule id from the context block that supports it. Example: [ultimate II.B.1].
- If the context does not contain the answer, say so plainly. Do NOT fill in from general knowledge.
- For questions that compare two sports, structure your answer by sport so the differences are obvious. If one sport's context doesn't address the topic, say that too.
- Be concise. One or two short paragraphs is usually enough."""

USER_TEMPLATE = """<context>
{context}
</context>

<question>{question}</question>

Answer using only the context above. Cite inline with [sport rule_id]."""


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
            header = f"[{c.sport} {c.rule_id}]"
        else:
            pages = (
                f"p.{c.page_start}"
                if c.page_start == c.page_end
                else f"pp.{c.page_start}-{c.page_end}"
            )
            header = f"[{c.sport} {c.rule_id} — {pages}]"
        blocks.append(f"{header}\n{c.text}")
    return "\n\n---\n\n".join(blocks)


def generate_answer(question: str, chunks: list[RetrievedChunk]) -> GeneratedAnswer:
    """Call Claude with the retrieved chunks and return the answer + usage.

    The call goes through llm-guardrails' ``guarded_call`` so cost caps
    and the event log fire uniformly. ``raise_on_truncation=False``
    keeps our existing behavior of returning the truncated text and
    surfacing ``stop_reason`` to the UI instead of raising.
    """
    client = Anthropic(api_key=settings.anthropic_api_key)
    context = format_context(chunks)
    hooks = [
        WindowedCapHook(app_state.cost_counter),
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
        system=SYSTEM_PROMPT,
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
