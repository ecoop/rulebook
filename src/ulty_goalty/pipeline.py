"""End-to-end: question -> answer + citations + raw retrieved chunks.

The module the API and the notebook both import. It hides the "is this a
single-sport or cross-sport question?" dispatch behind a single function
so callers don't have to make that decision themselves.
"""

from dataclasses import asdict, dataclass
from typing import Any

from .generate import generate_answer
from .retrieve import RetrievedChunk, retrieve, retrieve_across_sports

# The sports we index. Extend by dropping a new PDF into Rules/, adding
# it to SOURCES in scripts/build_index.py, and rebuilding.
DEFAULT_SPORTS = ["ultimate", "goaltimate"]


@dataclass
class AskResult:
    question: str
    answer: str
    chunks: list[RetrievedChunk]
    input_tokens: int
    output_tokens: int
    stop_reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "chunks": [asdict(c) for c in self.chunks],
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "stop_reason": self.stop_reason,
        }


def ask(
    question: str,
    *,
    sport: str | None = None,
    sports: list[str] | None = None,
    k: int = 5,
) -> AskResult:
    """Answer a question about disc-sport rules.

    Args:
        question: Natural-language question.
        sport: If set, retrieve ONLY from this sport (single-sport mode).
        sports: If set (and `sport` is None), retrieve k results from
            EACH of these sports and let the model compare. Defaults to
            all known sports.
        k: top-k retrieval size. Per-sport when in cross-sport mode.
    """
    if sport is not None:
        chunks = retrieve(question, sport=sport, k=k)
    else:
        chunks = retrieve_across_sports(question, sports or DEFAULT_SPORTS, k_per_sport=k)

    result = generate_answer(question, chunks)
    return AskResult(
        question=question,
        answer=result.answer,
        chunks=chunks,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        stop_reason=result.stop_reason,
    )
