"""FastAPI surface — a single POST /ask endpoint.

The endpoint returns not just the answer but also the retrieved chunks
that fed the model. That's the whole point of this project as a learning
artifact: the frontend can render the chunks alongside the answer so the
user can see how retrieval quality maps to answer quality. Watching a
wrong answer next to the chunks that produced it is worth more than any
diagram of "what RAG is".

The API is intentionally thin — all the interesting code lives in
src/ulty_goalty. If you want to swap providers, add reranking, or filter
by more metadata, do it there, not here.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from ulty_goalty.build_info import BUILD_INFO
from ulty_goalty.config import settings
from ulty_goalty.interaction_log import log_feedback, log_qa
from ulty_goalty.pipeline import DEFAULT_SPORTS, ask
from ulty_goalty.store import list_sports

app = FastAPI(title="ulty-goalty", description="RAG over disc-sport rules.")

# CORS — the Vite dev server runs on 5173 by default. In production you'd
# lock this down; for a local demo `*` is fine.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, description="Natural-language question about the rules.")
    sport: str | None = Field(
        default=None,
        description="Restrict retrieval to this sport (e.g. 'ultimate'). "
                    "Leave null to retrieve from every known sport and let the model compare.",
    )
    k: int = Field(default=5, ge=1, le=20, description="Top-k retrieval (per sport in cross-sport mode).")


class RetrievedChunkOut(BaseModel):
    text: str
    source: str
    sport: str
    rule_id: str
    page_start: int
    page_end: int
    distance: float


class AskResponse(BaseModel):
    qa_id: str = Field(..., description="Opaque id — pass this to POST /feedback to rate the answer.")
    question: str
    answer: str
    chunks: list[RetrievedChunkOut]
    input_tokens: int
    output_tokens: int
    model: str
    stop_reason: str = Field(..., description='"end_turn" if the model finished, "max_tokens" if truncated, etc.')


class FeedbackRequest(BaseModel):
    qa_id: str = Field(..., description="The qa_id returned from a prior /ask response.")
    rating: int = Field(..., ge=1, le=5, description="1 (very wrong) to 5 (perfect).")
    comment: str | None = Field(
        default=None,
        max_length=4000,
        description="Optional note — what was missing, wrong, or worth capturing.",
    )


class FeedbackResponse(BaseModel):
    ok: bool = True


class MetaResponse(BaseModel):
    sports: list[str]
    embedding_provider: str
    embedding_model: str
    claude_model: str
    build_sha: str = Field(..., description="Short git SHA at server start.")
    build_dirty: bool = Field(..., description="True if the working tree had uncommitted changes at start.")
    started_at: str = Field(..., description="ISO 8601 UTC timestamp when the server process started.")


@app.get("/meta", response_model=MetaResponse)
def meta() -> MetaResponse:
    """Small metadata endpoint the frontend hits on load — sports + models in use."""
    sports = list_sports(settings.resolved_index_path) or DEFAULT_SPORTS
    return MetaResponse(
        sports=sports,
        embedding_provider=settings.embedding_provider,
        embedding_model=settings.embedding_model,
        claude_model=settings.claude_model,
        build_sha=BUILD_INFO.sha,
        build_dirty=BUILD_INFO.dirty,
        started_at=BUILD_INFO.started_at,
    )


@app.post("/ask", response_model=AskResponse)
def ask_endpoint(req: AskRequest) -> AskResponse:
    try:
        result = ask(question=req.question, sport=req.sport, k=req.k)
    except RuntimeError as e:
        # e.g. "no index" — build_index.py hasn't been run yet
        raise HTTPException(status_code=503, detail=str(e)) from e

    qa_id = uuid.uuid4().hex
    chunks_out = [
        RetrievedChunkOut(
            text=c.text,
            source=c.source,
            sport=c.sport,
            rule_id=c.rule_id,
            page_start=c.page_start,
            page_end=c.page_end,
            distance=c.distance,
        )
        for c in result.chunks
    ]

    # Persist the full interaction so we can later mine downvoted answers
    # for corrections, upvoted ones for a "greatest hits" corpus, etc.
    log_qa(
        qa_id,
        question=result.question,
        sport=req.sport,
        k=req.k,
        answer=result.answer,
        chunks=[asdict(c) for c in result.chunks],
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        model=settings.claude_model,
    )

    return AskResponse(
        qa_id=qa_id,
        question=result.question,
        answer=result.answer,
        chunks=chunks_out,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        model=settings.claude_model,
        stop_reason=result.stop_reason,
    )


@app.post("/feedback", response_model=FeedbackResponse)
def feedback_endpoint(req: FeedbackRequest) -> FeedbackResponse:
    """Record a thumbs-up / thumbs-down on a prior answer.

    We don't validate that qa_id exists in the log — an unknown id just
    ends up as an orphan feedback row. That's fine for HITL work: the
    log is a data source to be joined and filtered, not a database with
    referential integrity to enforce.
    """
    log_feedback(req.qa_id, rating=req.rating, comment=req.comment)
    return FeedbackResponse()
