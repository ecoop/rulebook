# Phase 2: accounts, gating, and quotas

_Last updated: 2026-10-13_

**Status: plan, not built.** This is the technical plan for taking Rulebook from
an invite-only demo to a self-serve, Goaltimate-branded product whose LLM spend
is bounded and, eventually, paid for by a small number of subscribers. It is the
second of four phases:

1. **Gates** (no code): rules licensing with USA Goaltimate; a handful of user
   conversations.
2. **This document**: real accounts, admission gating, per-user quotas, a
   concise free tier, a quota-aware usage recap, and (2b) payments. Shipped as a
   web app / PWA.
3. iOS: a Capacitor wrapper around the same web app, in-app purchase,
   Sign in with Apple, offline rule browsing.
4. Expansion: Ultimate edition, team/league plans.

## Goals and non-goals

**Goals**

- Anyone can sign up; the operator controls how many people get in.
- LLM spend is capped by design, not by watching a dashboard. The free tier draws
  from a fixed weekly budget the operator sets.
- Users see their allowance in *questions*, never dollars.
- Free answers are shorter (cheaper); paid answers are full length.
- Payments (2b) plug in without reworking 2a, and the same entitlement model
  carries over to iOS in-app purchase in phase 3.

**Non-goals**

- Revenue. The target is break-even LLM spend, not income.
- An unlimited plan.
- Replacing the RAG pipeline, the numpy store, or GCS-hosted index/logs.

## Prerequisite: rules licensing

The app already shows rule text verbatim in the retrieved-passages panel, so a
commercial product needs written permission from the rules owner regardless of
anything below. The ask to USA Goaltimate should cover: (a) answering questions
from the rules, (b) displaying passages, (c) offline browsing of the full text in
the app, and (d) attribution requirements. Without (c), the browse feature becomes
"open the official rules" (a link out). Nothing in 2a depends on the answer,
but nothing should launch publicly before it.

## Economics this plan is built around

Measured from the production QA log on 2026-10-13 (27 questions, Sonnet 5):
**$0.0085 mean / $0.0155 p90 / $0.019 max per question**; output tokens are
~54% of cost; cross-domain questions cost ~2x single-domain. A
Goaltimate-only edition is single-domain. Planning figure: **$0.01 typical,
$0.02 worst case**.

Expected shape: many free users, very few paying. So the free tier is not derived
from paid surplus; it is a **fixed weekly pool** (`free_pool_usd_weekly`) that the
operator sets to what they're willing to spend, raised later as paid surplus
appears. Everything else follows from protecting that pool.

## Architecture changes

What stays: Cloud Run, FastAPI, the pipeline, GCS for the index/logs/rule docs,
llm-cost-governor's global caps as the last-resort backstop, and the RBAC model
(`roles.py`).

What's added:

| Concern | Today | Phase 2 |
|---|---|---|
| Identity | Invite token in a cookie (`guest_auth.InviteAuthMiddleware`) | **Firebase Auth** (email link + Google, and Sign in with Apple when iOS lands). Invite tokens stay for operators/existing testers |
| User records | `invite_tokens.json`, `roles.jsonl`, `allowed_domains.jsonl` in GCS | **Firestore** `users/{principal}` |
| Per-user limits | `cap_per_token_usd` in the in-memory `CostCounter` | **Firestore** transactional quota counters, in questions |
| Free-tier budget | Global `cap_weekly_usd` (all users) | Firestore weekly pool doc; global caps remain as the backstop |
| Branding | One app, all domains | **Edition** config (`goaltimate`) |

### Identity: one principal id for everything downstream

Everything downstream (roles, domain scoping, cost attribution, the engagement
counter, log `author` fields) keys off `guest.token`. Rather than threading a
second identity type through those call sites, add a resolver that turns a
verified Firebase ID token into the same shape, with a namespaced principal id:

- Invite-token users: `tok_…` (unchanged).
- Firebase users: `fb_<uid>`.

Implementation: a small auth layer in front of (or wrapping)
`InviteAuthMiddleware` that, when an `Authorization: Bearer <firebase-id-token>`
header or session cookie is present, verifies it with `firebase-admin` and sets
the same request-scoped guest that `get_current_guest()` returns. Callers don't
change. If `guest-auth` should own the multi-resolver logic, that is a change in
the `guest-auth` repo, a separate lane. Build it here first and extract later,
the pattern `tokens.py` already follows.

### Gating: admission is a role

Use the RBAC model rather than a parallel "status" flag:

- New role **`waitlisted`**: can sign in, see their place/status, and browse
  rules (if licensed); no `ask` capability.
- Self-signups get `waitlisted` (a new `SIGNUP_ROLE` setting); invite-token users
  keep `DEFAULT_ROLE = beginner`.
- **Admitting** someone = promoting `waitlisted → beginner`, which the Users tab
  already does. Add a bulk "admit next N" action.
- Admission paths, all optional:
  - **Invite codes**: an existing user or the operator mints a code (reuse
    `mint_token()`); redeeming it at signup admits immediately.
  - **Manual**: the Users tab.
  - **Automatic**: a scheduled job admits up to N per week while last week's
    pool utilization is under a threshold (e.g. 70%). This is what keeps "many
    free users" from outrunning the pool.

This keeps the operator's existing tools (Users tab, `/advanced/roles`) as the
admin surface.

### Data model (Firestore)

```
users/{principal}
  created_at, display_name, email (Firebase users only)
  role                     # replaces the roles.jsonl override for fb_ users
  allowed_domains          # default = edition domains
  plan: "free" | "player" | "captain"
  plan_source: "none" | "stripe" | "app_store"   # 2b / phase 3
  plan_expires_at
  invited_by               # principal, if admitted by invite code

usage/{principal}_{period_id}
  questions, usd, last_at   # period_id = ISO week for free, billing period for paid

pool/{iso_week}
  free_usd, free_questions, cap_usd

invites/{code}
  created_by, created_at, redeemed_by, redeemed_at
```

Invite-token users can stay in the GCS objects for now; the user-record
accessor (`roles.resolve_role`, `allowed_domains.resolve_allowed_domains`)
reads Firestore for `fb_` principals and the existing GCS sources for `tok_`.
Migrating the GCS records into Firestore can be a later cleanup.

Behind a `UserStore` protocol with `InMemoryUserStore` (tests, local dev) and
`FirestoreUserStore` (hosted), mirroring how `state_backend_kind` already
selects local vs GCS.

### Quotas

Plans are config, not code:

```python
PLANS = {
    "free":    Plan(questions=3,   period="week",  max_tokens=600,  concise=True),
    "player":  Plan(questions=75,  period="month", max_tokens=2048, concise=False),
    "captain": Plan(questions=200, period="month", max_tokens=2048, concise=False),
}
```

The numbers are placeholders, tuned after launch from real data. Operators and
admins bypass plan quotas (a capability, e.g. `quota.exempt`), but not the
global backstop.

`/ask` flow:

1. **Reserve** (Firestore transaction): check the user's period count against
   their plan; for `free`, also check `pool/{week}.free_usd < cap_usd`. If both
   pass, increment `questions` by 1. A refused request returns a typed 429
   (`quota_exhausted` or `free_pool_exhausted`) with `resets_at`, and the UI
   renders it as a message, not an error.
2. **Generate** with the plan's `max_tokens` and concise prompt variant.
3. **Settle**: add the actual USD (from the same pricing llm-cost-governor uses)
   to `usage.usd` and `pool.free_usd`. If generation fails, refund the
   reservation.

Reserving before the LLM call means two simultaneous requests can't both slip
under the limit. Counting in questions makes the user-facing number exact; the
USD fields are for the operator and for the pool.

Periods: free resets on a **fixed** boundary (Monday 00:00 UTC, displayed in
the user's local time) rather than llm-cost-governor's rolling week. A fixed
reset is easier to explain ("resets Monday"). Paid periods follow the billing
period.

Global backstop: keep `CostCounter` hourly/daily/weekly caps as is. They are
still per-instance in memory, which is why Cloud Run stays at
`--max-instances=1`. At this scale one instance with request concurrency is
enough (the work is I/O-bound waiting on the API). Moving the global caps onto a
shared backend is an llm-cost-governor change (separate repo), only needed if
traffic requires more than one instance.

### Concise free answers

`generate_answer()` gains `max_tokens` and a `concise` flag (supplied by the
plan). Concise mode appends one instruction to the system prompt, roughly:
"Answer in at most three sentences, then the citations." It also lowers
`max_tokens` so a long answer can't run up cost. The `max_tokens` value must
leave room for a complete answer: a truncated answer (`stop_reason ==
"max_tokens"`) is worse than a long one. Track the truncation rate per plan.

Before shipping, run the gold-answer set through both variants and compare
correctness and cost. That comparison is also the evidence for choosing the free
tier's `max_tokens`.

### Usage recap

New endpoint `GET /me/quota`:

```json
{
  "plan": "free",
  "questions_used": 2,
  "questions_limit": 3,
  "resets_at": "2026-10-19T00:00:00Z",
  "pool_open": true
}
```

- Ask page: a single line under the input, e.g. "1 of 3 free questions left ·
  resets Mon". When the pool is closed: "Free answers are used up for this week."
- Activity page: per-period history of questions (it already lists the user's
  own questions).
- The existing dollar-denominated Usage widget stays, gated to operators.

### Edition (Goaltimate branding)

`RULEBOOK_EDITION=goaltimate` selects:

- Backend: default `allowed_domains` for new users, signup role, plan table.
- Frontend (`VITE_EDITION` at build time): app name, colors, icon, copy, PWA
  manifest.

Deploy decision: a separate Cloud Run service from the same image, with its own
hostname. That keeps rulebook.cooper.nu as the multi-domain operator app. Per
the one-project-per-service convention, this probably means a new GCP project
(e.g. `goaltimate-prod`) with its own Firestore and state bucket. `deploy.sh` is
already env-driven (`RULEBOOK_PROJECT`, `RULEBOOK_SERVICE`).

Add `--min-instances=1` to the edition service so a first question mid-game
doesn't wait on a cold start (~$10–40/mo depending on CPU allocation).

### PWA

- Web app manifest and icons per edition.
- A service worker that caches the app shell. Offline rule browsing comes in
  phase 3, subject to licensing.
- An "Add to Home Screen" hint on iOS Safari, which has no install prompt.

### Account lifecycle and abuse

- **Deletion**: `DELETE /me` removes the Firestore user, usage docs, and the
  Firebase account. Log rows keep the question but replace `author` with
  `deleted`. Apple requires this in phase 3; build it now.
- **Privacy policy and terms**: static pages, linked at signup.
- **Abuse**: email verification before admission; the existing IP rate limit;
  Firebase App Check on web (App Attest on iOS later). The waitlist is the
  primary defense: new accounts get nothing until admitted.

### Logging

QA log schema v4 adds `plan`, `concise`, and `principal_kind` (`tok`/`fb`), so
cost per plan and truncation rate come straight from the log.

## 2b: payments

Only once 2a shows real usage.

- **RevenueCat** as the entitlement source, using its web billing (Stripe) now
  and App Store in phase 3, so one subscriber record covers both platforms.
- Webhook `POST /billing/revenuecat` (signature verified) updates
  `users/{principal}.plan`, `plan_source`, `plan_expires_at`.
- `/ask` reads the plan from the user record, never from the client.
- Price/plan copy shows questions per month, not dollars.

Paid surplus can then raise `free_pool_usd_weekly`. That is the only connection
between paid and free tiers.

## Work breakdown (PRs, in order)

| # | PR | Depends on |
|---|---|---|
| 1 | `UserStore` protocol + in-memory/Firestore impls; `fb_` principals readable by `resolve_role` / `resolve_allowed_domains` | — |
| 2 | Firebase ID-token resolver feeding `get_current_guest()`; frontend sign-in | 1 |
| 3 | `waitlisted` role, `SIGNUP_ROLE`, invite codes, bulk admit in Users tab | 1, 2 |
| 4 | Plan table, reserve/settle quotas, free pool, typed 429s | 1 |
| 5 | Concise mode in `generate_answer()` + gold-set comparison | — (can go first) |
| 6 | `GET /me/quota` + Ask-page quota line | 4 |
| 7 | Edition config + Goaltimate branding + PWA manifest/service worker | — |
| 8 | `DELETE /me`, privacy/terms pages, QA log v4 | 2, 4 |
| 9 | New service/project deploy, `--min-instances=1` | 1–8 |
| 10 | (2b) RevenueCat web billing + webhook | 4, 9 |

PR 5 is independent and can start at once.

## Open questions

- Free allowance: 3/week is a guess. Set it from the pool size and the measured
  share of admitted users who are active each week.
- Should invite codes come with a bonus allowance for both people? It's cheap
  growth, but it draws on the pool.
- Fold the existing invite-token users into Firestore now or later?
- Hostname for the edition.
