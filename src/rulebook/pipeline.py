"""End-to-end: question -> answer + citations + raw retrieved chunks.

The module the API and the notebook both import. It hides the "is this a
single-domain or cross-domain question?" dispatch behind a single function
so callers don't have to make that decision themselves.
"""

from dataclasses import asdict, dataclass, field
from typing import Any

from .generate import find_unverified_citations, generate_answer
from .retrieve import RetrievedChunk, retrieve, retrieve_across_domains

# Cold-start bootstrap ONLY. The domain set is otherwise derived from DATA:
# from the index (store.list_domains) at serve time, and from the discovered
# rules/<domain>/ dirs at build time. This fallback is used solely by /meta
# before any index exists, so a fresh dev env still shows something in the
# picker. Do NOT reintroduce it as the source of truth (see #110).
DEFAULT_DOMAINS = ["ultimate", "goaltimate"]


@dataclass
class AskResult:
    question: str
    answer: str
    chunks: list[RetrievedChunk]
    input_tokens: int
    output_tokens: int
    stop_reason: str
    # [domain rule_id] citations in `answer` that match no retrieved chunk (#172).
    unverified_citations: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "chunks": [asdict(c) for c in self.chunks],
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "stop_reason": self.stop_reason,
            "unverified_citations": self.unverified_citations,
        }


def ask(
    question: str,
    *,
    domain: str | None = None,
    domains: list[str] | None = None,
    k: int = 5,
) -> AskResult:
    """Answer a question about disc-domain rules.

    Args:
        question: Natural-language question.
        domain: If set, retrieve ONLY from this domain (single-domain mode).
        domains: If set (and `domain` is None), retrieve k results from
            EACH of these domains and let the model compare. Defaults to
            all known domains.
        k: top-k retrieval size. Per-domain when in cross-domain mode.
    """
    if domain is not None:
        chunks = retrieve(question, domain=domain, k=k)
    else:
        chunks = retrieve_across_domains(question, domains, k_per_domain=k)

    result = generate_answer(question, chunks)
    return AskResult(
        question=question,
        answer=result.answer,
        chunks=chunks,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        stop_reason=result.stop_reason,
        unverified_citations=find_unverified_citations(result.answer, chunks),
    )
