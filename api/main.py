"""FastAPI surface — a single POST /ask endpoint.

The endpoint returns not just the answer but also the retrieved chunks
that fed the model. That's the whole point of this project as a learning
artifact: the frontend can render the chunks alongside the answer so the
user can see how retrieval quality maps to answer quality. Watching a
wrong answer next to the chunks that produced it is worth more than any
diagram of "what RAG is".

The API is intentionally thin — all the interesting code lives in
src/rulebook. If you want to swap providers, add reranking, or filter
by more metadata, do it there, not here.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from rulebook.build_info import BUILD_INFO
from rulebook.config import settings
from rulebook.interaction_log import (
    log_feedback,
    log_gold,
    log_gold_curation,
    log_qa,
    read_latest_curation,
    read_latest_golds,
)
from rulebook.pipeline import DEFAULT_SPORTS, ask
from rulebook.store import list_sports

app = FastAPI(title="rulebook", description="RAG over disc-sport rules.")

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
    tags: list[str] = Field(
        default_factory=list,
        description="Issue tags — small taxonomy chosen by the client; stored as-is.",
    )
    comment: str | None = Field(
        default=None,
        max_length=4000,
        description="Optional note — what worked, what didn't, worth capturing for later review.",
    )


class FeedbackResponse(BaseModel):
    ok: bool = True


class GoldRequest(BaseModel):
    qa_id: str = Field(..., description="The qa_id returned from a prior /ask response.")
    question: str = Field(..., min_length=1, description="Original question, duplicated for self-contained gold rows.")
    gold_answer: str = Field(..., min_length=1, max_length=20000, description="User-authored canonical answer, markdown.")


class GoldResponse(BaseModel):
    ok: bool = True


class AdminGoldRow(BaseModel):
    qa_id: str
    question: str
    gold_answer: str
    timestamp: str
    included: bool = Field(..., description="Whether this gold is included in the next index rebuild.")


class AdminGoldListResponse(BaseModel):
    golds: list[AdminGoldRow]


class GoldCurationRequest(BaseModel):
    qa_id: str
    included: bool


class GoldCurationResponse(BaseModel):
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
    log_feedback(req.qa_id, rating=req.rating, comment=req.comment, tags=req.tags)
    return FeedbackResponse()


@app.post("/gold", response_model=GoldResponse)
def gold_endpoint(req: GoldRequest) -> GoldResponse:
    """Record a user-authored canonical answer for a prior qa_id.

    Golds are picked up by scripts/build_index.py on the next rebuild —
    each gold becomes retrievable chunks tagged by sport (via ## Sport
    markdown headings) or as a shared/all-sports chunk if the answer
    has no headings.
    """
    log_gold(req.qa_id, question=req.question, gold_answer=req.gold_answer)
    return GoldResponse()


@app.get("/admin/golds", response_model=AdminGoldListResponse)
def admin_list_golds() -> AdminGoldListResponse:
    """Merged view of gold.jsonl + gold_curation.jsonl.

    Latest gold per qa_id joined with latest curation decision (default
    included=True when no curation row exists).
    """
    curation = read_latest_curation()
    rows = [
        AdminGoldRow(
            qa_id=g["qa_id"],
            question=g["question"],
            gold_answer=g["gold_answer"],
            timestamp=g["timestamp"],
            included=curation.get(g["qa_id"], True),
        )
        for g in read_latest_golds()
    ]
    return AdminGoldListResponse(golds=rows)


@app.post("/admin/gold-curation", response_model=GoldCurationResponse)
def admin_set_gold_curation(req: GoldCurationRequest) -> GoldCurationResponse:
    """Toggle whether a gold is included in the next index rebuild."""
    log_gold_curation(req.qa_id, included=req.included)
    return GoldCurationResponse()
