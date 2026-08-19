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

import subprocess
import sys
import time
import uuid
from dataclasses import asdict
from datetime import UTC

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from guest_auth import InviteAuthMiddleware, get_current_guest
from llm_cost_governor.counters import (
    _week_of,  # canonical Monday-UTC week key; matches the cost counter's weekly buckets
)
from pydantic import BaseModel, Field

# Wire the guardrails singletons BEFORE anything Depends()-related runs.
# Rulebook has a single-file API so ordering inside this module is
# sufficient — see rulebook/app_state.py for the multi-file case.
from rulebook import app_state  # noqa: E402
from rulebook.allowed_sports import (  # noqa: E402
    ALL_SENTINEL,
    append_allowed_sports_row,
    constrain_sports,
    grants_from_rows,
    read_allowed_sports_rows,
    resolve_allowed_sports,
)
from rulebook.allowed_sports import RESET_SENTINEL as SPORTS_RESET_SENTINEL  # noqa: E402
from rulebook.build_info import BUILD_INFO
from rulebook.config import settings
from rulebook.index_sync import sync_index_from_gcs
from rulebook.log_sync import sync_logs_from_gcs

app_state.initialize(settings)

# Hosted (gcs) deploys don't ship the index in the image and can't write
# under repo_root; pull it into the writable INDEX_PATH before any request.
# No-op in local dev (state_backend_kind="local"); best-effort otherwise.
sync_index_from_gcs()

# Same story for the append-only JSONL logs: on gcs the log dir is ephemeral
# /tmp, so pull prior feedback/gold/qa rows in at boot. Each append then
# writes through to GCS (interaction_log._append). No-op in local dev.
sync_logs_from_gcs()

from jsonl_log import utc_now_iso  # noqa: E402

from rulebook.interaction_log import (  # noqa: E402
    count_comments_by_author,
    count_golds_by_author,
    count_questions_by_author,
    log_audit,
    log_feedback,
    log_gold,
    log_gold_curation,
    log_qa,
    log_source_curation,
    read_audit,
    read_latest_curation,
    read_latest_feedback,
    read_latest_golds,
    read_latest_source_curation,
    read_qa_entries,
    read_qa_questions,
)
from rulebook.pipeline import DEFAULT_SPORTS, ask  # noqa: E402
from rulebook.roles import (  # noqa: E402
    CAP_ACTIVITY_VIEW,
    CAP_ASK,
    CAP_ATTRIBUTION_VIEW,
    CAP_FEEDBACK_COMMENT,
    CAP_FEEDBACK_TAG,
    CAP_FEEDBACK_VIEW,
    CAP_FEEDBACK_VIEW_ALL,
    CAP_GOLD_AUTHOR,
    CAP_GOLDS_CLONE,
    CAP_GOLDS_CURATE,
    CAP_GOLDS_VIEW,
    CAP_GOLDS_VIEW_ALL,
    CAP_INDEX_REBUILD,
    CAP_QUESTIONS_VIEW_ALL,
    CAP_RATE,
    CAP_SOURCES_CURATE,
    CAP_SOURCES_VIEW,
    CAP_USERS_ADD,
    CAP_USERS_CHANGE_ROLE,
    CAP_USERS_REMOVE,
    CAP_USERS_RENAME,
    CAP_USERS_VIEW,
    RESET_SENTINEL,
    ROLE_CAPABILITIES,
    ROLE_LADDER,
    append_role_row,
    capabilities_for,
    has_capability,
    is_valid_role,
    level_number,
    overrides_from_rows,
    read_role_rows,
    require_capability,
    resolve_role,
    role_fingerprint,
)
from rulebook.store import list_sports  # noqa: E402
from rulebook.tokens import (  # noqa: E402
    mint_token,
    read_tokens_object,
    write_tokens_object,
)

app = FastAPI(title="rulebook", description="RAG over disc-sport rules.")

# CORS — the Vite dev server runs on 5173 by default. In production you'd
# lock this down; for a local demo `*` is fine.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Invite-token gate. Off by default (RULEBOOK_DEMO_MODE unset/false)
# so local dev and any public deploy keep the current no-auth
# behaviour — the middleware is a complete pass-through in that
# case. When on, the settings object supplies both `demo_mode` and
# `invite_tokens` via the GuestAuthConfig Protocol; attribute access
# happens at request time so runtime mutations (tests, hot reload)
# take effect on the live app. No welcome_html override — the
# library's built-in "invite-only" fallback is fine for now; swap in
# rendered markdown here if we ever want a real welcome page.
app.add_middleware(InviteAuthMiddleware, config=settings)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, description="Natural-language question about the rules.")
    sport: str | None = Field(
        default=None,
        description="Single-ruleset mode (e.g. 'ultimate'). Back-compat alias; "
                    "prefer `sports`. Takes precedence if set.",
    )
    sports: list[str] | None = Field(
        default=None,
        description="Cross-ruleset mode: retrieve from exactly this subset and let the "
                    "model compare. Empty/null (and no `sport`) = every ruleset in the index.",
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
        max_length=400,
        description="Optional note — what worked, what didn't. Capped short (400) to keep feedback terse; see rbac-capabilities.md.",
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
    gold_id: str = Field(..., description="Stable id for this gold (legacy golds: == qa_id).")
    qa_id: str
    question: str
    gold_answer: str
    author: str | None = Field(default=None, description="Who authored this gold (recipient label).")
    is_own: bool = Field(..., description="Whether the current caller authored it — drives Edit vs Clone.")
    timestamp: str
    included: bool = Field(..., description="Whether this gold is included in the next index rebuild.")


class AdminGoldListResponse(BaseModel):
    golds: list[AdminGoldRow]


class GoldCurationRequest(BaseModel):
    gold_id: str
    included: bool


class CloneGoldResponse(BaseModel):
    gold_id: str = Field(..., description="Id of the new gold, now owned by the caller.")
    ok: bool = True


class AuditRow(BaseModel):
    timestamp: str
    actor: str | None = None
    actor_fingerprint: str | None = Field(default=None, description="Actor's capability-set fingerprint at the time.")
    action: str = Field(..., description="The capability the write exercised, e.g. 'golds.curate'.")
    target: str | None = Field(default=None, description="Affected id — gold_id, source path, token…")
    detail: dict = Field(default_factory=dict, description="Before→after specifics.")


class AuditListResponse(BaseModel):
    audit: list[AuditRow]


class GoldCurationResponse(BaseModel):
    ok: bool = True


class AdminFeedbackRow(BaseModel):
    qa_id: str
    timestamp: str
    rating: int
    tags: list[str] = Field(default_factory=list)
    comment: str | None = None
    question: str = Field(..., description="From qa_log; may be empty for orphan feedback rows.")
    has_gold: bool = Field(..., description="True if the user has authored a gold answer for this qa_id.")
    is_own: bool = Field(..., description="Whether the current caller authored it — gates inline Edit.")
    author: str | None = Field(default=None, description="Who left this feedback; shown to view-all readers (L5+).")


class AdminFeedbackListResponse(BaseModel):
    feedback: list[AdminFeedbackRow]


class AdminQuestionRow(BaseModel):
    qa_id: str
    question: str
    answer: str = Field(..., description="The stored answer, so you can revisit it.")
    sport: str | None = None
    sports: list[str] = Field(
        default_factory=list,
        description="Rulesets the query ran against (v4+ rows). Empty for older rows; "
                    "fall back to `sport` there.",
    )
    timestamp: str
    rating: int | None = Field(default=None, description="Your rating for this Q&A, if you gave one.")
    has_gold: bool = Field(..., description="True if you've authored a gold for this qa_id.")
    is_own: bool = Field(..., description="Whether the current caller asked it — gates the inline Add-gold action.")
    author: str | None = Field(default=None, description="Who asked; shown to view-all readers (L5+).")


class AdminQuestionListResponse(BaseModel):
    questions: list[AdminQuestionRow]


class AdminSourceRow(BaseModel):
    path: str = Field(..., description="Repo-relative posix path, e.g. 'rules/ultimate/strategy.md'.")
    sport: str
    size_bytes: int
    modified_at: str = Field(..., description="ISO 8601 UTC of the file's last mtime.")
    included: bool = Field(..., description="Whether this file is included in the next index rebuild.")


class AdminSourceListResponse(BaseModel):
    sources: list[AdminSourceRow]


class SourceCurationRequest(BaseModel):
    path: str = Field(..., description="Repo-relative posix path to include/exclude.")
    included: bool


class SourceCurationResponse(BaseModel):
    ok: bool = True


class RebuildIndexResponse(BaseModel):
    ok: bool
    duration_seconds: float
    stdout_tail: str = Field(..., description="Last few lines of build_index.py output — for the UI to show a build summary.")
    stderr_tail: str = Field(..., description="Last few lines of stderr if the build failed; empty on success.")


class IndexInfoResponse(BaseModel):
    """Provenance of the live index, read from its manifest (all null before a
    stamped build exists)."""
    build_id: str | None = None
    built_at: str | None = None
    git_sha: str | None = None
    build_num: str | None = None
    count: int = 0
    dimension: int = 0
    sports: list[str] = Field(default_factory=list)
    gold_answers: int = 0
    gold_chunks: int = 0
    sources: list[dict] = Field(default_factory=list)
    golds: list[dict] = Field(default_factory=list)
    chunks_by_sport: dict[str, int] = Field(default_factory=dict)


class IndexBuildRow(BaseModel):
    build_id: str | None = None
    built_at: str | None = None
    git_sha: str | None = None
    build_num: str | None = None
    count: int = 0
    gold_answers: int = 0
    gold_chunks: int = 0
    sources: list[dict] = Field(default_factory=list)
    golds: list[dict] = Field(default_factory=list)


class IndexBuildsResponse(BaseModel):
    active_build_id: str | None = None
    builds: list[IndexBuildRow] = Field(default_factory=list)


class MeResponse(BaseModel):
    recipient: str | None = Field(
        default=None,
        description="Guest label; null outside demo_mode / when unauthenticated.",
    )
    role: str = Field(..., description="Effective role — a level id, level0 (suspended) … level8 (superuser).")
    level: int = Field(..., description="Numeric level 0–8, for ordering and the level badge.")
    fingerprint: str = Field(..., description="8-hex fingerprint of this role's capability set — changes iff its permissions change.")
    capabilities: list[str] = Field(
        default_factory=list,
        description="Sorted capability strings the effective role grants. The UI renders tabs/columns/buttons off these; the backend enforces them per-endpoint.",
    )
    allowed_sports: list[str] | None = Field(
        default=None,
        description="Rulesets this caller may ask against (#112); null = unrestricted (all, "
                    "including any added later). The picker filters to this set.",
    )
    demo_mode: bool = Field(..., description="Whether the invite gate is active.")


class RoleAssignmentOut(BaseModel):
    token: str
    role: str
    source: str = Field(..., description='"override" (roles.jsonl) or "seed" (env).')
    fingerprint: str = Field(..., description="8-hex fingerprint of the role's capability set.")


class AdminRolesResponse(BaseModel):
    roles: list[RoleAssignmentOut]
    ladder: list[str] = Field(..., description="Role tiers low→high.")


class RoleChangeRequest(BaseModel):
    token: str = Field(..., min_length=1, description="The guest token whose role is being set.")
    role: str = Field(..., description="One of the ladder tiers.")
    note: str | None = Field(default=None, max_length=2000, description="Optional audit note.")


class RoleChangeResponse(BaseModel):
    ok: bool = True
    token: str
    role: str = Field(..., description="Effective role after the change.")


class AllowedSportsOut(BaseModel):
    token: str
    sports: list[str] | None = Field(
        default=None,
        description="Rulesets granted to this token; null = all (the '*' grant).",
    )
    source: str = Field(..., description='"override" (log) | "seed" (env) | "default".')


class AdminAllowedSportsResponse(BaseModel):
    grants: list[AllowedSportsOut]
    all_sports: list[str] = Field(
        ..., description="Every ruleset in the index — the unfiltered grant menu."
    )


class AllowedSportsChangeRequest(BaseModel):
    token: str = Field(..., min_length=1, description="The guest token whose access is being set.")
    sports: list[str] = Field(
        ...,
        description="Exact rulesets to grant. [] revokes all; ['*'] grants all (incl. future).",
    )
    note: str | None = Field(default=None, max_length=2000, description="Optional audit note.")


class AllowedSportsChangeResponse(BaseModel):
    ok: bool = True
    token: str
    sports: list[str] | None = Field(..., description="Effective allowlist after the change; null = all.")


class InviteTokenOut(BaseModel):
    token: str
    label: str = Field(..., description="Human-readable recipient label.")
    last_seen: str | None = Field(
        None,
        description="ISO timestamp of this user's most recent authenticated visit (/me) or question; null if never seen since tracking began.",
    )
    weekly_usd: float = Field(0.0, description="This user's spend this week (Mon-reset, USD).")
    weekly_tokens: int = Field(0, description="This user's input+output tokens this week (Mon-reset).")
    questions: int = Field(0, description="Lifetime count of questions this user has asked.")
    comments: int = Field(0, description="Lifetime count of answers this user has commented on.")
    golds: int = Field(0, description="Lifetime count of gold answers this user owns.")


class InviteTokensResponse(BaseModel):
    tokens: list[InviteTokenOut]


class AddInviteTokenRequest(BaseModel):
    label: str = Field(..., min_length=1, description="Recipient label, e.g. 'alice'.")
    token: str | None = Field(default=None, description="Optional explicit token; minted if omitted.")


class AddInviteTokenResponse(BaseModel):
    token: str
    label: str


class RemoveInviteTokenResponse(BaseModel):
    ok: bool = True
    token: str
    label: str


class RenameInviteTokenRequest(BaseModel):
    label: str = Field(..., min_length=1, description="New recipient label for an existing token.")


class MetaResponse(BaseModel):
    sports: list[str]
    embedding_provider: str
    embedding_model: str
    claude_model: str
    build_sha: str = Field(..., description="Short git SHA at server start.")
    build_num: str = Field(..., description="Monotonic commit count (rev-list --count HEAD); '?' if unavailable.")
    build_dirty: bool = Field(..., description="True if the working tree had uncommitted changes at start.")
    started_at: str = Field(..., description="ISO 8601 UTC timestamp when the server process started.")


class DiagnosticsResponse(BaseModel):
    """Live runtime stats for the Diagnostics widget."""
    chunk_count: int
    dimension: int
    chunks_by_sport: dict[str, int]
    index_built_at: str | None = Field(
        default=None,
        description="ISO 8601 UTC mtime of the manifest.json; None if no index yet.",
    )
    gold_count: int = Field(..., description="Distinct qa_ids with a gold answer.")
    feedback_count: int = Field(..., description="Distinct qa_ids with any feedback.")
    source_file_count: int = Field(..., description="Files under rules/<sport>/ eligible for ingest.")


class UsageCaps(BaseModel):
    hourly_usd: float
    daily_usd: float
    weekly_usd: float
    per_token_usd: float


class UsageResponse(BaseModel):
    """Current CostCounter snapshot for the Usage widget."""
    hourly_usd: float
    daily_usd: float
    weekly_usd: float
    caps: UsageCaps
    caller_weekly_usd: float | None = Field(
        default=None,
        description="This caller's cumulative weekly spend against per_token_usd. Populated only when guest-auth identifies a caller (demo_mode=true + valid invite cookie); None otherwise.",
    )
    guardrails_enabled: bool = Field(
        ..., description="Whether the caps are actually being enforced (else the panel is informational only)."
    )
    per_provider_usd: dict[str, float] = Field(
        default_factory=dict,
        description="In-memory per-provider USD totals since the server started. Resets on restart.",
    )
    guest_recipient: str | None = Field(
        default=None,
        description="Human-readable label for the current invite token, if any. Powers the Demo widget's 'Signed in as ...' line.",
    )


@app.get("/meta", response_model=MetaResponse)
def meta() -> MetaResponse:
    """Small metadata endpoint the frontend hits on load — sports + models in use."""
    sports = list_sports(settings.resolved_index_path) or DEFAULT_SPORTS
    # Scope the ruleset list to what the caller may ask against (#112), so a
    # restricted user's picker only offers their rulesets and they don't even
    # learn the others exist. None = unrestricted (public deploy / no identity).
    guest = get_current_guest()
    allowed = resolve_allowed_sports(guest.token if guest else None)
    if allowed is not None:
        sports = [s for s in sports if s in allowed]
    return MetaResponse(
        sports=sports,
        embedding_provider=settings.embedding_provider,
        embedding_model=settings.embedding_model,
        claude_model=settings.claude_model,
        build_sha=BUILD_INFO.sha,
        build_num=BUILD_INFO.build_num,
        build_dirty=BUILD_INFO.dirty,
        started_at=BUILD_INFO.started_at,
    )


@app.get("/diagnostics", response_model=DiagnosticsResponse)
def diagnostics_endpoint() -> DiagnosticsResponse:
    """Live runtime stats for the Diagnostics widget.

    Reads index metadata, chunk log rows, and the source directory
    directly — no aggregation cache. Fast enough because the numbers
    are all small.
    """
    import json as _json
    from collections import Counter
    from datetime import datetime

    from scripts.build_index import discover_sources

    index_path = settings.resolved_index_path
    manifest_path = index_path / "manifest.json"

    chunk_count = 0
    dimension = 0
    chunks_by_sport: dict[str, int] = {}
    index_built_at: str | None = None
    if manifest_path.exists():
        manifest = _json.loads(manifest_path.read_text())
        chunk_count = int(manifest.get("count", 0))
        dimension = int(manifest.get("dimension", 0))
        index_built_at = datetime.fromtimestamp(
            manifest_path.stat().st_mtime, tz=UTC
        ).isoformat(timespec="seconds")

        chunks_path = index_path / "chunks.jsonl"
        if chunks_path.exists():
            sports = Counter()
            with chunks_path.open() as f:
                for line in f:
                    row = _json.loads(line)
                    sports[row["sport"]] += 1
            chunks_by_sport = dict(sports)

    gold_count = len(read_latest_golds())
    feedback_count = len(read_latest_feedback())
    source_file_count = len(
        discover_sources(settings.rules_dir, apply_curation=False)
    )

    return DiagnosticsResponse(
        chunk_count=chunk_count,
        dimension=dimension,
        chunks_by_sport=chunks_by_sport,
        index_built_at=index_built_at,
        gold_count=gold_count,
        feedback_count=feedback_count,
        source_file_count=source_file_count,
    )


@app.get("/usage", response_model=UsageResponse)
def usage_endpoint() -> UsageResponse:
    """Current spend snapshot from the llm-cost-governor CostCounter.

    Feeds the Usage floating widget. Passes the current guest's token
    (when demo_mode is on and the caller is identified) to
    snapshot_for(), so caller_weekly_usd populates against the
    per-guest weekly cap. Outside demo_mode / for unidentified
    callers, token is None and only the global windows are returned —
    same privacy boundary as before (no per-token detail leaks).
    """
    guest = get_current_guest()
    snap = app_state.cost_counter.snapshot_for(guest.token if guest else None)
    return UsageResponse(
        hourly_usd=snap["hourly_usd"],
        daily_usd=snap["daily_usd"],
        weekly_usd=snap["weekly_usd"],
        caps=UsageCaps(**snap["caps"]),
        caller_weekly_usd=snap.get("caller_weekly_usd"),
        guardrails_enabled=settings.guardrails_enabled,
        per_provider_usd=(app_state.provider_totals.snapshot() if app_state.provider_totals else {}),
        guest_recipient=(guest.recipient if guest else None),
    )


@app.post(
    "/ask",
    response_model=AskResponse,
    dependencies=[
        Depends(app_state.enforce_ip_rate_limit),
        Depends(require_capability(CAP_ASK)),
    ],
)
def ask_endpoint(req: AskRequest) -> AskResponse:
    # Per-user ruleset access (#112): constrain the request to the caller's
    # allowlist BEFORE retrieval. The frontend already filters the picker, but
    # the boundary is enforced here regardless — a scoped caller must never
    # reach the unmasked global search. allowed=None means unrestricted.
    guest = get_current_guest()
    allowed = resolve_allowed_sports(guest.token if guest else None)
    call_sport, call_sports = req.sport, req.sports
    if allowed is not None:
        if req.sport is not None:
            if req.sport not in allowed:
                raise HTTPException(status_code=403, detail=f"ruleset '{req.sport}' not permitted")
        else:
            try:
                # Empty selection = "all I'm allowed" (a concrete list), never
                # the global all — so the sport=None search path stays unreached.
                call_sports = constrain_sports(req.sports, allowed)
            except PermissionError as e:
                raise HTTPException(status_code=403, detail=str(e)) from e

    try:
        result = ask(question=req.question, sport=call_sport, sports=call_sports, k=req.k)
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
    # The exact rulesets this query ran against (post-allowlist constraint):
    # the effective subset, else the singular sport, else every ruleset.
    effective_sports = call_sports or (
        [call_sport] if call_sport else list_sports(settings.resolved_index_path)
    )
    log_qa(
        qa_id,
        question=result.question,
        sport=call_sport,
        sports=effective_sports,
        k=req.k,
        answer=result.answer,
        chunks=[asdict(c) for c in result.chunks],
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        model=settings.claude_model,
        stop_reason=result.stop_reason,
        author=(guest.recipient if guest else None),
    )

    # Engagement tally for the Users tab's "this week" column. USD is recorded
    # separately by the WindowedCapHook during generation; here we attribute
    # the raw token count to the caller. Updates last_seen too.
    if guest is not None and app_state.token_counter is not None:
        app_state.token_counter.record(
            result.input_tokens + result.output_tokens, token=guest.token
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


@app.post(
    "/feedback",
    response_model=FeedbackResponse,
    dependencies=[Depends(require_capability(CAP_RATE))],
)
def feedback_endpoint(req: FeedbackRequest) -> FeedbackResponse:
    """Record a thumbs-up / thumbs-down on a prior answer.

    We don't validate that qa_id exists in the log — an unknown id just
    ends up as an orphan feedback row. That's fine for HITL work: the
    log is a data source to be joined and filtered, not a database with
    referential integrity to enforce.

    Partial permission (docs/rbac-capabilities.md §4): a bare rating is the
    casual tier (#1); issue *tags* need `feedback.tag` (also #1), a free-text
    *comment* needs `feedback.comment` (#2+). Enforced per-field so a lower rung
    can still tag without commenting.
    """
    guest = get_current_guest()
    if (req.tags or req.comment) and settings.demo_mode:
        role = resolve_role(guest.token if guest else None)
        if req.tags and not has_capability(role, CAP_FEEDBACK_TAG):
            raise HTTPException(
                status_code=403,
                detail="tags require the 'feedback.tag' capability; a bare rating is allowed",
            )
        if req.comment and not has_capability(role, CAP_FEEDBACK_COMMENT):
            raise HTTPException(
                status_code=403,
                detail="a comment requires the 'feedback.comment' capability; a rating (with tags) is allowed",
            )
    log_feedback(
        req.qa_id,
        rating=req.rating,
        comment=req.comment,
        tags=req.tags,
        author=(guest.recipient if guest else None),
    )
    return FeedbackResponse()


@app.post(
    "/gold",
    response_model=GoldResponse,
    dependencies=[Depends(require_capability(CAP_GOLD_AUTHOR))],
)
def gold_endpoint(req: GoldRequest) -> GoldResponse:
    """Author (or update) the caller's own gold for a qa_id.

    Ownership is intrinsic: this upserts the caller's *own* gold for the
    qa_id — it reuses their existing gold's id if they have one, else mints a
    new one, and never touches another author's gold. To fork someone else's
    gold, use POST /advanced/golds/{gold_id}/clone. Golds are picked up by
    scripts/build_index.py on the next rebuild.
    """
    guest = get_current_guest()
    author = guest.recipient if guest else None
    mine = next(
        (g for g in read_latest_golds() if g["qa_id"] == req.qa_id and g.get("author") == author),
        None,
    )
    gold_id = mine["gold_id"] if mine else uuid.uuid4().hex
    log_gold(
        req.qa_id,
        gold_id=gold_id,
        question=req.question,
        gold_answer=req.gold_answer,
        author=author,
    )
    return GoldResponse()


@app.get(
    "/me",
    response_model=MeResponse,
    dependencies=[Depends(require_capability(CAP_ASK))],
)
def me_endpoint() -> MeResponse:
    """Current guest's identity + effective role + capabilities — powers UI gating.

    Gated on `ask` (which every non-suspended role has), so a `suspended`
    guest gets 403 here — the frontend renders the suspended screen on that.
    Outside demo_mode there's no guest: recipient is null and role is the
    novice default.
    """
    guest = get_current_guest()
    # "Last seen" (Option A): the frontend calls /me once per page load, so
    # touching the tally here (0 tokens) records a visit even for lurkers who
    # open their invite link but never ask — exactly who we want to spot.
    if guest is not None and app_state.token_counter is not None:
        app_state.token_counter.record(0, token=guest.token)
    role = resolve_role(guest.token if guest else None)
    return MeResponse(
        recipient=(guest.recipient if guest else None),
        role=role,
        level=level_number(role),
        fingerprint=role_fingerprint(role),
        capabilities=sorted(capabilities_for(role)),
        allowed_sports=resolve_allowed_sports(guest.token if guest else None),
        demo_mode=settings.demo_mode,
    )


def _require_gcs_for_roles() -> tuple[str, str]:
    if settings.state_backend_kind != "gcs" or not settings.gcs_state_bucket:
        raise HTTPException(
            status_code=400,
            detail="role changes require the gcs state backend (RULEBOOK_STATE_BACKEND=gcs).",
        )
    return settings.gcs_state_bucket, settings.roles_object


@app.get(
    "/advanced/roles",
    response_model=AdminRolesResponse,
    dependencies=[Depends(require_capability(CAP_USERS_VIEW))],
)
def admin_list_roles() -> AdminRolesResponse:
    """Merged role assignments (env seed ⊕ live roles.jsonl overrides)."""
    merged: dict[str, tuple[str, str]] = {
        tok: (role, "seed") for tok, role in settings.initial_roles.items()
    }
    if settings.state_backend_kind == "gcs" and settings.gcs_state_bucket:
        overrides = overrides_from_rows(
            read_role_rows(settings.gcs_state_bucket, settings.roles_object)
        )
        for tok, role in overrides.items():
            merged[tok] = (role, "override")
    rows = [
        RoleAssignmentOut(token=tok, role=role, source=src, fingerprint=role_fingerprint(role))
        for tok, (role, src) in sorted(merged.items())
    ]
    return AdminRolesResponse(roles=rows, ladder=list(ROLE_LADDER))


@app.post(
    "/advanced/roles",
    response_model=RoleChangeResponse,
    dependencies=[Depends(require_capability(CAP_USERS_CHANGE_ROLE))],
)
def admin_set_role(req: RoleChangeRequest) -> RoleChangeResponse:
    """Append a role change to roles.jsonl. Takes effect within the TTL."""
    if not is_valid_role(req.role):
        raise HTTPException(
            status_code=422,
            detail=f"invalid role '{req.role}'; one of {sorted(ROLE_CAPABILITIES)}",
        )
    bucket, obj = _require_gcs_for_roles()
    guest = get_current_guest()
    append_role_row(
        bucket,
        obj,
        {
            "v": 1,
            "timestamp": utc_now_iso(),
            "token": req.token,
            "role": req.role,
            "changed_by": (guest.recipient if guest else None),
            "note": req.note,
        },
    )
    _audit(CAP_USERS_CHANGE_ROLE, target=req.token, detail={"role": req.role})
    return RoleChangeResponse(token=req.token, role=req.role)


@app.post(
    "/advanced/roles/{token}/reset",
    response_model=RoleChangeResponse,
    dependencies=[Depends(require_capability(CAP_USERS_CHANGE_ROLE))],
)
def admin_reset_role(token: str) -> RoleChangeResponse:
    """Clear a token's override; role falls back to the env seed (or novice)."""
    bucket, obj = _require_gcs_for_roles()
    guest = get_current_guest()
    append_role_row(
        bucket,
        obj,
        {
            "v": 1,
            "timestamp": utc_now_iso(),
            "token": token,
            "role": RESET_SENTINEL,
            "changed_by": (guest.recipient if guest else None),
            "note": None,
        },
    )
    _audit(CAP_USERS_CHANGE_ROLE, target=token, detail={"role": "reset"})
    return RoleChangeResponse(token=token, role=resolve_role(token))


def _require_gcs_for_allowed_sports() -> tuple[str, str]:
    if settings.state_backend_kind != "gcs" or not settings.gcs_state_bucket:
        raise HTTPException(
            status_code=400,
            detail="ruleset-access changes require the gcs state backend (RULEBOOK_STATE_BACKEND=gcs).",
        )
    return settings.gcs_state_bucket, settings.allowed_sports_object


@app.get(
    "/advanced/allowed-sports",
    response_model=AdminAllowedSportsResponse,
    dependencies=[Depends(require_capability(CAP_USERS_VIEW))],
)
def admin_list_allowed_sports() -> AdminAllowedSportsResponse:
    """Per-user ruleset allowlists (#112), one row per known user.

    Effective allowlist = override (allowed_sports.jsonl) ▸ seed (env) ▸
    default. Enumerates every invite token plus any token carrying an explicit
    grant, so the Users tab has a row to edit for each user. `all_sports` is the
    UNFILTERED menu — an operator grants from the full corpus, not their own
    (possibly scoped) view.
    """
    all_sports = list_sports(settings.resolved_index_path) or DEFAULT_SPORTS
    known: set[str] = set(settings.invite_tokens) | set(settings.initial_allowed_sports)
    overrides: dict[str, list[str] | str] = {}
    if settings.state_backend_kind == "gcs" and settings.gcs_state_bucket:
        overrides = grants_from_rows(
            read_allowed_sports_rows(settings.gcs_state_bucket, settings.allowed_sports_object)
        )
        known |= set(overrides)

    def _row(tok: str) -> AllowedSportsOut:
        if tok in overrides:
            grant, source = overrides[tok], "override"
        elif tok in settings.initial_allowed_sports:
            grant, source = settings.initial_allowed_sports[tok], "seed"
        else:
            grant, source = list(settings.default_allowed_sports), "default"
        sports = None if grant == ALL_SENTINEL else list(grant)
        return AllowedSportsOut(token=tok, sports=sports, source=source)

    return AdminAllowedSportsResponse(
        grants=[_row(tok) for tok in sorted(known)],
        all_sports=all_sports,
    )


@app.post(
    "/advanced/allowed-sports",
    response_model=AllowedSportsChangeResponse,
    dependencies=[Depends(require_capability(CAP_USERS_CHANGE_ROLE))],
)
def admin_set_allowed_sports(req: AllowedSportsChangeRequest) -> AllowedSportsChangeResponse:
    """Grant a token an exact ruleset allowlist. Takes effect within the TTL.

    Same capability as role assignment (#112). `['*']` stores the all-grant;
    otherwise every named ruleset must exist in the corpus (no granting a
    ruleset that isn't there).
    """
    bucket, obj = _require_gcs_for_allowed_sports()
    all_sports = set(list_sports(settings.resolved_index_path) or DEFAULT_SPORTS)
    if req.sports == [ALL_SENTINEL]:
        stored: list[str] | str = ALL_SENTINEL
    else:
        unknown = [s for s in req.sports if s not in all_sports]
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"unknown ruleset(s) {unknown}; one of {sorted(all_sports)}",
            )
        stored = list(req.sports)
    guest = get_current_guest()
    append_allowed_sports_row(
        bucket,
        obj,
        {
            "v": 1,
            "timestamp": utc_now_iso(),
            "token": req.token,
            "sports": stored,
            "changed_by": (guest.recipient if guest else None),
            "note": req.note,
        },
    )
    _audit(CAP_USERS_CHANGE_ROLE, target=req.token, detail={"sports": stored})
    return AllowedSportsChangeResponse(
        token=req.token, sports=None if stored == ALL_SENTINEL else stored
    )


@app.post(
    "/advanced/allowed-sports/{token}/reset",
    response_model=AllowedSportsChangeResponse,
    dependencies=[Depends(require_capability(CAP_USERS_CHANGE_ROLE))],
)
def admin_reset_allowed_sports(token: str) -> AllowedSportsChangeResponse:
    """Clear a token's grant; allowlist falls back to the seed (or default)."""
    bucket, obj = _require_gcs_for_allowed_sports()
    guest = get_current_guest()
    append_allowed_sports_row(
        bucket,
        obj,
        {
            "v": 1,
            "timestamp": utc_now_iso(),
            "token": token,
            "sports": SPORTS_RESET_SENTINEL,
            "changed_by": (guest.recipient if guest else None),
            "note": None,
        },
    )
    _audit(CAP_USERS_CHANGE_ROLE, target=token, detail={"sports": "reset"})
    return AllowedSportsChangeResponse(token=token, sports=resolve_allowed_sports(token))


def _require_gcs_for_invite_tokens() -> tuple[str, str]:
    if settings.state_backend_kind != "gcs" or not settings.gcs_state_bucket:
        raise HTTPException(
            status_code=400,
            detail="invite-token management requires the gcs state backend.",
        )
    return settings.gcs_state_bucket, settings.invite_tokens_object


def _usage_by_token() -> dict[str, dict]:
    """Per-token engagement for the Users tab: this week's $ + tokens + last seen.

    This is a superuser-gated surface (the caller already sees every token),
    so keying by raw invite token here is acceptable — unlike the public
    /usage panel, which must never expose the per-token map.
    """
    per_usd: dict[str, float] = {}
    if app_state.cost_counter is not None:
        per_usd = app_state.cost_counter.current_usage().get("per_token", {})
    tok_table: dict[str, dict] = {}
    if app_state.token_counter is not None:
        tok_table = app_state.token_counter.to_dict().get("dimensions", {}).get("token", {})

    week = _week_of()
    out: dict[str, dict] = {}
    for tok in set(per_usd) | set(tok_table):
        stat = tok_table.get(tok, {})
        this_week = stat.get("week_of") == week
        out[tok] = {
            "weekly_usd": round(per_usd.get(tok, 0.0), 4),
            "weekly_tokens": int(stat.get("amount_cumulative_week", 0)) if this_week else 0,
            "last_seen": stat.get("last_seen"),
        }
    return out


@app.get(
    "/advanced/invite-tokens",
    response_model=InviteTokensResponse,
    dependencies=[Depends(require_capability(CAP_USERS_VIEW))],
)
def admin_list_invite_tokens() -> InviteTokensResponse:
    """Current GCS invite allowlist + per-user engagement. Powers the Users tab."""
    bucket, obj = _require_gcs_for_invite_tokens()
    tokens = read_tokens_object(bucket, obj)
    usage = _usage_by_token()
    # Activity counts key on the author *label*, not the token; join by label.
    questions = count_questions_by_author()
    comments = count_comments_by_author()
    golds = count_golds_by_author()
    return InviteTokensResponse(
        tokens=[
            InviteTokenOut(
                token=tok,
                label=label,
                last_seen=usage.get(tok, {}).get("last_seen"),
                weekly_usd=usage.get(tok, {}).get("weekly_usd", 0.0),
                weekly_tokens=usage.get(tok, {}).get("weekly_tokens", 0),
                questions=questions.get(label, 0),
                comments=comments.get(label, 0),
                golds=golds.get(label, 0),
            )
            for tok, label in sorted(tokens.items(), key=lambda kv: kv[1])
        ]
    )


@app.post(
    "/advanced/invite-tokens",
    response_model=AddInviteTokenResponse,
    dependencies=[Depends(require_capability(CAP_USERS_ADD))],
)
def admin_add_invite_token(req: AddInviteTokenRequest) -> AddInviteTokenResponse:
    """Create a user: mint (or accept) a token and add it to the allowlist.

    Takes effect within the token source's TTL — immediately on this
    instance (cache is dropped on write), within ~30s elsewhere.
    """
    bucket, obj = _require_gcs_for_invite_tokens()
    tokens = read_tokens_object(bucket, obj)
    token = req.token or mint_token()
    if token in tokens:
        raise HTTPException(status_code=409, detail=f"token already exists ({tokens[token]!r}).")
    tokens[token] = req.label
    write_tokens_object(bucket, obj, tokens)
    _audit(CAP_USERS_ADD, target=token, detail={"label": req.label})
    return AddInviteTokenResponse(token=token, label=req.label)


@app.delete(
    "/advanced/invite-tokens/{token}",
    response_model=RemoveInviteTokenResponse,
    dependencies=[Depends(require_capability(CAP_USERS_REMOVE))],
)
def admin_remove_invite_token(token: str) -> RemoveInviteTokenResponse:
    """Remove a user from the allowlist (their cookie stops resolving).

    Note: this is hard removal. For a reversible, audit-preserving block,
    set the user's role to `suspended` via /advanced/roles instead.
    """
    bucket, obj = _require_gcs_for_invite_tokens()
    tokens = read_tokens_object(bucket, obj)
    if token not in tokens:
        raise HTTPException(status_code=404, detail="token not found.")
    label = tokens.pop(token)
    write_tokens_object(bucket, obj, tokens)
    _audit(CAP_USERS_REMOVE, target=token, detail={"label": label})
    return RemoveInviteTokenResponse(token=token, label=label)


@app.patch(
    "/advanced/invite-tokens/{token}",
    response_model=InviteTokenOut,
    dependencies=[Depends(require_capability(CAP_USERS_RENAME))],
)
def admin_rename_invite_token(token: str, req: RenameInviteTokenRequest) -> InviteTokenOut:
    """Rename a user's label, keeping the same token.

    The token (identity) is unchanged, so the person's access, cookie, and
    per-guest cost are unaffected — only the display label updates. Past log
    rows keep the old label (audit trail). To hand a token to a *different*
    person, remove it and mint a fresh one instead (see docs/demo-mode.md, #20).
    """
    bucket, obj = _require_gcs_for_invite_tokens()
    tokens = read_tokens_object(bucket, obj)
    if token not in tokens:
        raise HTTPException(status_code=404, detail="token not found.")
    tokens[token] = req.label
    write_tokens_object(bucket, obj, tokens)
    _audit(CAP_USERS_RENAME, target=token, detail={"label": req.label})
    return InviteTokenOut(token=token, label=req.label)


def _view_scope(view_all_cap: str) -> tuple[bool, str | None]:
    """Self/all scoping for an Advanced list (docs/rbac-capabilities.md §5).

    Returns (see_all, author): with the `.all` capability the caller sees
    everyone's rows (True, None); otherwise only their own, matched on the
    author label stored with each row (False, <recipient>).
    """
    guest = get_current_guest()
    role = resolve_role(guest.token if guest else None)
    if has_capability(role, view_all_cap):
        return True, None
    return False, (guest.recipient if guest else None)


def _audit(action: str, *, target: str | None = None, detail: dict | None = None) -> None:
    """Record a shared-state mutation to the audit trail (§5). Call AFTER the
    write succeeds so only committed actions are logged."""
    guest = get_current_guest()
    role = resolve_role(guest.token if guest else None)
    log_audit(
        actor=(guest.recipient if guest else None),
        action=action,
        target=target,
        detail=detail,
        actor_fingerprint=role_fingerprint(role),
    )


@app.get("/advanced/golds", response_model=AdminGoldListResponse, dependencies=[Depends(require_capability(CAP_GOLDS_VIEW))])
def admin_list_golds() -> AdminGoldListResponse:
    """Merged view of gold.jsonl + gold_curation.jsonl.

    Latest gold per qa_id joined with latest curation decision (default
    included=True when no curation row exists). Self-scoped without
    `golds.view.all`: the caller sees only golds they authored.
    """
    curation = read_latest_curation()
    guest = get_current_guest()
    me_author = guest.recipient if guest else None
    see_all = has_capability(resolve_role(guest.token if guest else None), CAP_GOLDS_VIEW_ALL)
    golds = read_latest_golds()
    if not see_all:
        golds = [g for g in golds if g.get("author") == me_author]
    rows = [
        AdminGoldRow(
            gold_id=g["gold_id"],
            qa_id=g["qa_id"],
            question=g["question"],
            gold_answer=g["gold_answer"],
            author=g.get("author"),
            is_own=g.get("author") == me_author,
            timestamp=g["timestamp"],
            included=curation.get(g["gold_id"], True),
        )
        for g in golds
    ]
    return AdminGoldListResponse(golds=rows)


@app.post("/advanced/gold-curation", response_model=GoldCurationResponse, dependencies=[Depends(require_capability(CAP_GOLDS_CURATE))])
def admin_set_gold_curation(req: GoldCurationRequest) -> GoldCurationResponse:
    """Toggle whether a specific gold is included in the next index rebuild."""
    log_gold_curation(req.gold_id, included=req.included)
    _audit(CAP_GOLDS_CURATE, target=req.gold_id, detail={"included": req.included})
    return GoldCurationResponse()


@app.post(
    "/advanced/golds/{gold_id}/clone",
    response_model=CloneGoldResponse,
    dependencies=[Depends(require_capability(CAP_GOLDS_CLONE))],
)
def admin_clone_gold(gold_id: str) -> CloneGoldResponse:
    """Fork a gold into a new one owned by the caller (docs/rbac-capabilities.md §5).

    Nothing is edited in place — the source gold is untouched; the caller gets
    their own copy (same qa_id + question + text, new id, author = caller),
    which they can then edit as their own. This is how #6 (operator) acts on
    another user's gold: clone, then edit the clone.
    """
    src = next((g for g in read_latest_golds() if g["gold_id"] == gold_id), None)
    if src is None:
        raise HTTPException(status_code=404, detail="gold not found.")
    guest = get_current_guest()
    new_id = uuid.uuid4().hex
    log_gold(
        src["qa_id"],
        gold_id=new_id,
        question=src["question"],
        gold_answer=src["gold_answer"],
        author=(guest.recipient if guest else None),
    )
    _audit(CAP_GOLDS_CLONE, target=gold_id, detail={"new_gold_id": new_id})
    return CloneGoldResponse(gold_id=new_id)


@app.get(
    "/advanced/audit",
    response_model=AuditListResponse,
    dependencies=[Depends(require_capability(CAP_ATTRIBUTION_VIEW))],
)
def admin_list_audit(limit: int = 200) -> AuditListResponse:
    """Recent shared-state mutations, newest-first.

    Gated on `attribution.view` (level 6+): seeing who did what is the same
    trust tier as seeing who authored what (the §5 attribution wall).
    """
    rows = [
        AuditRow(
            timestamp=r["timestamp"],
            actor=r.get("actor"),
            actor_fingerprint=r.get("actor_fingerprint"),
            action=r["action"],
            target=r.get("target"),
            detail=r.get("detail") or {},
        )
        for r in read_audit(limit=limit)
    ]
    return AuditListResponse(audit=rows)


@app.get("/advanced/feedback", response_model=AdminFeedbackListResponse, dependencies=[Depends(require_capability(CAP_FEEDBACK_VIEW))])
def admin_list_feedback() -> AdminFeedbackListResponse:
    """List the latest feedback event per qa_id, sorted newest-first.

    Joins with qa_log for the question text and with the gold log so the
    UI can flag which rated answers already have a curator-authored
    correction. Legacy v1 (binary up/down) feedback rows are filtered
    out — they don't have tag/comment fields and would render as noise.
    Self-scoped without `feedback.view.all`: the caller sees only feedback
    they authored.
    """
    questions = read_qa_questions()
    gold_qa_ids = {g["qa_id"] for g in read_latest_golds()}

    see_all, author = _view_scope(CAP_FEEDBACK_VIEW_ALL)
    # is_own compares against the caller's own label regardless of scope — a
    # view-all reader still only gets Edit on the rows they authored.
    guest = get_current_guest()
    me_author = guest.recipient if guest else None
    rows: list[AdminFeedbackRow] = []
    for r in read_latest_feedback():
        if not see_all and r.get("author") != author:
            continue
        rows.append(
            AdminFeedbackRow(
                qa_id=r["qa_id"],
                timestamp=r["timestamp"],
                rating=int(r["rating"]),
                tags=list(r.get("tags") or []),
                comment=r.get("comment"),
                question=questions.get(r["qa_id"], ""),
                has_gold=r["qa_id"] in gold_qa_ids,
                is_own=r.get("author") == me_author,
                author=r.get("author"),
            )
        )
    return AdminFeedbackListResponse(feedback=rows)


@app.get("/advanced/questions", response_model=AdminQuestionListResponse, dependencies=[Depends(require_capability(CAP_ACTIVITY_VIEW))])
def admin_list_questions() -> AdminQuestionListResponse:
    """Asked questions, newest-first — the "my questions" history (#51).

    Self-scoped by default (`activity.view`, level 1+): you see only the
    questions you asked. With `questions.view.all` (Reviewer, level 5+) you
    see everyone's, each stamped with its author — the same self→all slice the
    feedback/gold lists use, and the tier where row authorship becomes visible.

    The rating / has_gold flags are the *caller's own* action status (have I
    rated / golded this), so `is_own` also gates the inline Add-gold action to
    your own questions.
    """
    see_all, _ = _view_scope(CAP_QUESTIONS_VIEW_ALL)
    guest = get_current_guest()
    me_author = guest.recipient if guest else None
    my_ratings = {
        f["qa_id"]: int(f["rating"])
        for f in read_latest_feedback()
        if f.get("author") == me_author
    }
    my_golds = {g["qa_id"] for g in read_latest_golds() if g.get("author") == me_author}
    rows = [
        AdminQuestionRow(
            qa_id=r["qa_id"],
            question=r.get("question", ""),
            answer=r.get("answer", ""),
            sport=r.get("sport"),
            sports=r.get("sports") or [],
            timestamp=r["timestamp"],
            rating=my_ratings.get(r["qa_id"]),
            has_gold=r["qa_id"] in my_golds,
            is_own=r.get("author") == me_author,
            author=r.get("author"),
        )
        for r in read_qa_entries()
        if see_all or r.get("author") == me_author
    ]
    return AdminQuestionListResponse(questions=rows)


@app.get("/advanced/sources", response_model=AdminSourceListResponse, dependencies=[Depends(require_capability(CAP_SOURCES_VIEW))])
def admin_list_sources() -> AdminSourceListResponse:
    """List every source file under rules/<sport>/ with its inclusion state.

    Passes apply_curation=False to discover_sources so both included AND
    excluded files show up in the admin table — the exclusion is
    surfaced via the ``included`` field so the UI can render a toggle.
    """
    from datetime import datetime

    from scripts.build_index import discover_sources

    rules_root = settings.rules_dir
    curation = read_latest_source_curation()

    rows: list[AdminSourceRow] = []
    for src in discover_sources(rules_root, apply_curation=False):
        # Identity is "rules/<sport>/<file>" — kept stable (independent of
        # where rules_dir resolves) so source-curation keys keep matching.
        rel = (Path("rules") / src.path.relative_to(rules_root)).as_posix()
        st = src.path.stat()
        rows.append(
            AdminSourceRow(
                path=rel,
                sport=src.sport,
                size_bytes=st.st_size,
                modified_at=datetime.fromtimestamp(st.st_mtime, tz=UTC).isoformat(timespec="seconds"),
                included=curation.get(rel, True),
            )
        )
    return AdminSourceListResponse(sources=rows)


@app.post("/advanced/source-curation", response_model=SourceCurationResponse, dependencies=[Depends(require_capability(CAP_SOURCES_CURATE))])
def admin_set_source_curation(req: SourceCurationRequest) -> SourceCurationResponse:
    """Toggle whether a source file is included in the next index rebuild."""
    log_source_curation(req.path, included=req.included)
    _audit(CAP_SOURCES_CURATE, target=req.path, detail={"included": req.included})
    return SourceCurationResponse()


@app.post("/advanced/rebuild-index", response_model=RebuildIndexResponse, dependencies=[Depends(require_capability(CAP_INDEX_REBUILD))])
def admin_rebuild_index() -> RebuildIndexResponse:
    """Run scripts/build_index.py synchronously and return its outcome.

    Blocks while the build runs — typically 15s but occasionally 60-90s
    when Voyage is slow to respond. The 300s subprocess timeout is a
    backstop against a truly stuck rebuild, not a normal ceiling.
    Client-side UI should disable the trigger button until this returns.

    Concurrent /ask requests during a rebuild will read the store file
    mid-write in the worst case; on a single-user local tool that race
    is vanishingly unlikely — noted as a real concern only if this
    ever goes multi-user.
    """
    started = time.monotonic()
    # api/main.py lives at <root>/api/main.py in both the repo and the /app
    # image, so derive the app root from __file__. settings.repo_root can't be
    # used here: once rulebook is pip-installed it resolves to a site-packages
    # ancestor (/opt/venv/…), where scripts/ doesn't exist — the rebuild button
    # failed with "can't open …/scripts/build_index.py".
    app_root = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [sys.executable, str(app_root / "scripts" / "build_index.py")],
        cwd=str(app_root),
        capture_output=True,
        text=True,
        timeout=300,
    )
    elapsed = time.monotonic() - started

    def _tail(s: str, lines: int = 20) -> str:
        return "\n".join(s.strip().splitlines()[-lines:])

    ok = proc.returncode == 0
    _audit(CAP_INDEX_REBUILD, detail={"ok": ok, "duration_seconds": round(elapsed, 2)})
    return RebuildIndexResponse(
        ok=ok,
        duration_seconds=round(elapsed, 2),
        stdout_tail=_tail(proc.stdout),
        stderr_tail=_tail(proc.stderr) if proc.returncode != 0 else "",
    )


@app.get(
    "/advanced/index-info",
    response_model=IndexInfoResponse,
    dependencies=[Depends(require_capability(CAP_INDEX_REBUILD))],
)
def admin_index_info() -> IndexInfoResponse:
    """Provenance of the live index, from its manifest — powers the
    'Current index' line so the running index is self-describing (#77)."""
    import json

    from rulebook.store import MANIFEST_FILE

    path = settings.resolved_index_path / MANIFEST_FILE
    if not path.exists():
        return IndexInfoResponse()
    try:
        d = json.loads(path.read_text())
    except (OSError, ValueError):
        return IndexInfoResponse()
    return IndexInfoResponse(
        build_id=d.get("build_id"),
        built_at=d.get("built_at"),
        git_sha=d.get("git_sha"),
        build_num=d.get("build_num"),
        count=d.get("count", 0),
        dimension=d.get("dimension", 0),
        sports=d.get("sports", []),
        gold_answers=d.get("gold_answers", 0),
        gold_chunks=d.get("gold_chunks", 0),
        sources=d.get("sources", []),
        golds=d.get("golds", []),
        chunks_by_sport=d.get("chunks_by_sport", {}),
    )


@app.get(
    "/advanced/index-builds",
    response_model=IndexBuildsResponse,
    dependencies=[Depends(require_capability(CAP_INDEX_REBUILD))],
)
def admin_index_builds() -> IndexBuildsResponse:
    """Durable index-build history (Indices tab list), newest first, active
    build flagged. Synthesizes a row for the live index if it predates history
    logging, so the list is never empty when an index exists."""
    from rulebook.interaction_log import read_index_builds

    def _row(d: dict) -> IndexBuildRow:
        return IndexBuildRow(
            build_id=d.get("build_id"),
            built_at=d.get("built_at"),
            git_sha=d.get("git_sha"),
            build_num=d.get("build_num"),
            count=d.get("count", 0),
            gold_answers=d.get("gold_answers", 0),
            gold_chunks=d.get("gold_chunks", 0),
            sources=d.get("sources", []),
            golds=d.get("golds", []),
        )

    info = admin_index_info()
    rows = [_row(b) for b in read_index_builds(limit=50)]
    if info.build_id and not any(r.build_id == info.build_id for r in rows):
        rows.insert(
            0,
            IndexBuildRow(
                build_id=info.build_id,
                built_at=info.built_at,
                git_sha=info.git_sha,
                build_num=info.build_num,
                count=info.count,
                gold_answers=info.gold_answers,
                gold_chunks=info.gold_chunks,
                sources=info.sources,
                golds=info.golds,
            ),
        )
    return IndexBuildsResponse(active_build_id=info.build_id, builds=rows)


# ── Web bundle (production only) ──────────────────────────────────────────────
# Mount LAST so all API routes take precedence. Vite dev serves the frontend
# itself and proxies /ask etc. back to this server; in that mode web/dist/
# doesn't exist and this mount is skipped silently. In the container, the
# multi-stage build produces web/dist/ and this mount hands its files to
# any non-API GET request. html=True serves index.html at the mount root.
#
# CWD-relative rather than settings.repo_root — an installed (non-editable)
# package resolves .repo_root to the site-packages ancestor, not the repo.
# Both `uv run` in dev and the container's WORKDIR=/app have web/dist
# under CWD, so this works in both modes.
from pathlib import Path  # noqa: E402

from fastapi.staticfiles import StaticFiles  # noqa: E402

_web_dist = Path("web/dist").resolve()
if _web_dist.is_dir():
    app.mount("/", StaticFiles(directory=_web_dist, html=True), name="web")
