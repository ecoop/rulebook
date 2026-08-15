import { useEffect, useMemo, useRef, useState } from 'react'
import { PanelRightOpen } from 'lucide-react'
import {
  FloatingWidgetStack,
  LayoutProvider,
  StackOriginReporter,
  type FloatingWidgetStackHandle,
  type WidgetDef,
} from '@nobadeer/floating-widgets'

import { UsageBody, UsageSummaryLine, type UsageSnapshot } from './widgets/Usage'
import {
  DiagnosticsBody,
  DiagnosticsSummaryLine,
  type DiagnosticsSnapshot,
} from './widgets/Diagnostics'
import { LevelBadge } from './levels'
import { HowItWorks } from './HowItWorks'

// -----------------------------------------------------------------------------
// Types mirroring the FastAPI response shape. Kept inline (rather than in a
// separate types file) so the whole client is legible in one screen.
// -----------------------------------------------------------------------------

interface Chunk {
  text: string
  source: string
  sport: string
  rule_id: string
  page_start: number
  page_end: number
  distance: number
}

interface AskResponse {
  qa_id: string
  question: string
  answer: string
  chunks: Chunk[]
  input_tokens: number
  output_tokens: number
  model: string
  stop_reason: string
}

type Rating = 1 | 2 | 3 | 4 | 5

const RATING_LABELS: Record<Rating, string> = {
  1: 'very wrong',
  2: 'mostly wrong',
  3: 'mixed / missing key nuance',
  4: 'mostly right',
  5: 'perfect',
}

// Issue tags — a small, action-oriented taxonomy. Multi-select. The
// point isn't to fully classify every answer; it's to separate failure
// modes that need different downstream fixes (correction vs corpus
// augmentation vs retrieval tuning vs prompt tuning).
type IssueTag = 'wrong' | 'incomplete' | 'retrieval' | 'format'

const TAG_LABELS: Record<IssueTag, string> = {
  wrong: 'wrong facts — needs correction',
  incomplete: 'missing context — corpus needs more info',
  retrieval: 'wrong passages retrieved — retrieval quality issue',
  format: 'facts right, delivery off — prompt tuning',
}

const TAGS: IssueTag[] = ['wrong', 'incomplete', 'retrieval', 'format']

// Bundle passed to each floating widget's header/render function.
// Kept as a plain object (view-model), NOT a place to call hooks.
interface WidgetCtx {
  usage: UsageSnapshot | null
  diag: DiagnosticsSnapshot | null
}

interface Meta {
  sports: string[]
  embedding_provider: string
  embedding_model: string
  claude_model: string
  build_sha: string
  build_num?: string
  build_dirty: boolean
  started_at: string
}

// Effective role for the current guest — powers UI gating (roles.md step 4).
// The ladder is monotonic; gating only applies in demo_mode (a public/dev
// deploy has no identities, so everything stays visible, matching the backend
// which no-ops role checks when demo_mode is off).
interface Me {
  recipient: string | null
  role: string
  level: number
  capabilities: string[]
  demo_mode: boolean
}

// Gating is by capability, not rank (docs/rbac-capabilities.md §6): /me returns
// the caller's `capabilities`; the UI shows a control iff the bundle grants it.

// Format the ISO server-start timestamp for the footer. Uses the viewer's
// locale so a bug reporter sees a time they can reason about.
function formatStartedAt(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// -----------------------------------------------------------------------------
// The whole UI is a single page: question box + sport picker on top, the
// answer in the middle, retrieved chunks below. Making the chunks visible is
// the whole point — the user can see WHY the model answered what it did.
// -----------------------------------------------------------------------------

export default function App() {
  const [question, setQuestion] = useState('')
  const [sport, setSport] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<AskResponse | null>(null)
  const [meta, setMeta] = useState<Meta | null>(null)
  const [sourcesOpen, setSourcesOpen] = useState(true)
  // Rating + tags + comment state is scoped to the *current* result — clearing
  // on new submissions so a prior vote never bleeds onto a new answer.
  const [rating, setRating] = useState<Rating | null>(null)
  const [tags, setTags] = useState<Set<IssueTag>>(() => new Set())
  const [comment, setComment] = useState('')
  // The comment "state" we last successfully sent. Used to compute whether
  // there are unsent edits so the Save-note button can hide when there's
  // nothing to save.
  const [savedComment, setSavedComment] = useState('')
  const [ratingError, setRatingError] = useState<string | null>(null)
  // Gold answer state — pre-populated with the model's original answer, so
  // the user's task is "edit what's wrong" rather than "author from scratch".
  const [gold, setGold] = useState('')
  const [savedGold, setSavedGold] = useState('')
  const [goldError, setGoldError] = useState<string | null>(null)
  const [goldSaving, setGoldSaving] = useState(false)
  // Widget snapshots. Fetched on mount, refreshed after every /ask so
  // Usage and Diagnostics reflect live state without a page reload.
  const [usage, setUsage] = useState<UsageSnapshot | null>(null)
  const [diag, setDiag] = useState<DiagnosticsSnapshot | null>(null)
  // Current guest's effective role (UI gating) + suspended flag.
  const [me, setMe] = useState<Me | null>(null)
  const [meForbidden, setMeForbidden] = useState(false)
  const [showHowItWorks, setShowHowItWorks] = useState(false)
  const headerRef = useRef<HTMLElement>(null)
  const stackRef = useRef<FloatingWidgetStackHandle>(null)

  useEffect(() => {
    fetch('/meta')
      .then((r) => (r.ok ? r.json() : Promise.reject(r.statusText)))
      .then(setMeta)
      .catch(() => {
        // Non-fatal — the app is still usable, we just won't populate the
        // sport dropdown from the server's view.
      })
    void refreshMe()
    void refreshWidgetData()
  }, [])

  async function refreshMe() {
    // /me is gated at novice, so a 403 means the guest is suspended — render
    // the suspended screen instead of the app. Other failures are non-fatal:
    // we don't gate (the backend still enforces).
    try {
      const resp = await fetch('/me')
      if (resp.status === 403) {
        setMeForbidden(true)
        return
      }
      if (!resp.ok) return
      setMe(await resp.json())
    } catch {
      /* ignore */
    }
  }

  async function refreshWidgetData() {
    // Fetches for the widgets. Called on mount and after every /ask so
    // Usage/Diagnostics reflect live state. Errors swallowed silently —
    // widget shows "Loading…" indefinitely rather than breaking the app.
    try {
      const [u, d] = await Promise.all([
        fetch('/usage').then((r) => (r.ok ? r.json() : null)),
        fetch('/diagnostics').then((r) => (r.ok ? r.json() : null)),
      ])
      if (u) setUsage(u)
      if (d) setDiag(d)
    } catch {
      /* ignore */
    }
  }

  async function sendFeedback(
    nextRating: Rating,
    nextTags: Set<IssueTag>,
    commentToSend: string,
  ) {
    if (!result) return
    // Optimistic: reflect the click immediately, revert on error. This is
    // a low-stakes personal-tool interaction — the fast feedback is worth
    // more than waiting for the network round-trip.
    const previousRating = rating
    const previousTags = tags
    const previousSavedComment = savedComment
    setRating(nextRating)
    setTags(nextTags)
    setSavedComment(commentToSend)
    setRatingError(null)
    try {
      const resp = await fetch('/feedback', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          qa_id: result.qa_id,
          rating: nextRating,
          tags: [...nextTags],
          comment: commentToSend.trim() ? commentToSend : null,
        }),
      })
      if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`)
    } catch (err) {
      setRating(previousRating)
      setTags(previousTags)
      setSavedComment(previousSavedComment)
      setRatingError(err instanceof Error ? err.message : String(err))
    }
  }

  async function saveGold() {
    if (!result || !gold.trim() || goldSaving) return
    setGoldSaving(true)
    setGoldError(null)
    try {
      const resp = await fetch('/gold', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          qa_id: result.qa_id,
          question: result.question,
          gold_answer: gold,
        }),
      })
      if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`)
      setSavedGold(gold)
    } catch (err) {
      setGoldError(err instanceof Error ? err.message : String(err))
    } finally {
      setGoldSaving(false)
    }
  }

  function toggleTag(tag: IssueTag) {
    if (rating == null) return
    const next = new Set(tags)
    if (next.has(tag)) next.delete(tag)
    else next.add(tag)
    sendFeedback(rating, next, comment)
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!question.trim() || loading) return
    setLoading(true)
    setError(null)
    setResult(null)
    setRating(null)
    setTags(new Set())
    setComment('')
    setSavedComment('')
    setRatingError(null)
    setGold('')
    setSavedGold('')
    setGoldError(null)
    try {
      const resp = await fetch('/ask', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          question,
          sport: sport || null,
          k: 5,
        }),
      })
      if (!resp.ok) {
        const body = await resp.text()
        throw new Error(`${resp.status}: ${body}`)
      }
      const data: AskResponse = await resp.json()
      setResult(data)
      // Seed the gold field with the model's own answer so the user's
      // task is editing, not authoring — see design discussion in commit
      // history for gold-answer feature.
      setGold(data.answer)
      setSavedGold('')
      // The ask just moved the cost counter — refresh Usage widget.
      void refreshWidgetData()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  // Widget context — the bundle of live state passed to each widget's
  // header/render function. Rebuilt each render; the registry never
  // closes over live state directly (see @nobadeer/floating-widgets
  // README for why).
  const widgetCtx: WidgetCtx = { usage, diag }

  // Widget registry. Order = stack order (top to bottom). useMemo with
  // an empty dep list makes the array reference stable so the stack
  // doesn't remount widgets each render.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const widgets = useMemo<WidgetDef<WidgetCtx>[]>(
    () => [
      {
        id: 'usage',
        header: (c) => <UsageSummaryLine usage={c.usage} />,
        render: (c) => <UsageBody usage={c.usage} />,
      },
      {
        id: 'diagnostics',
        defaultCollapsed: true,
        header: (c) => <DiagnosticsSummaryLine diag={c.diag} />,
        render: (c) => <DiagnosticsBody diag={c.diag} />,
      },
    ],
    [],
  )

  // UI gating by capability, active only in demo_mode. Authoring golds needs
  // `gold.author` (level 3+); the Advanced link needs `advanced.view` (level 4+).
  const gatingActive = !!me && me.demo_mode
  const canEvaluate = !gatingActive || (me != null && me.capabilities.includes('gold.author'))
  const showAdminLink = !!me && (!me.demo_mode || me.capabilities.includes('advanced.view'))

  if (meForbidden) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background px-6 text-center text-foreground">
        <div className="max-w-md space-y-2">
          <h1 className="text-xl font-medium">Access suspended</h1>
          <p className="text-sm text-muted-foreground">
            Your access to Rulebook has been suspended. If you think this is a
            mistake, contact whoever sent your invite.
          </p>
        </div>
      </div>
    )
  }

  return (
    <LayoutProvider>
      <StackOriginReporter headerRef={headerRef} />
      <div className="min-h-screen bg-background text-foreground">
        <header ref={headerRef} className="border-b border-border bg-card">
          <div className="flex items-start justify-between gap-4 px-6 py-4">
            <div className="min-w-0">
              <h1 className="text-xl font-medium">Rulebook</h1>
              <p className="text-sm text-muted-foreground">
                Ask about the rules of ultimate and goaltimate. Answers cite the actual rule numbers.
              </p>
              {meta && (
                <p className="text-sm text-muted-foreground">
                  build{' '}
                  <span className="opacity-70">
                    {meta.build_num && `${meta.build_num} (`}
                    <span
                      className="font-mono"
                      title={
                        meta.build_dirty
                          ? 'Uncommitted changes were present at server start'
                          : `Commit ${meta.build_sha}`
                      }
                    >
                      {meta.build_sha}
                      {meta.build_dirty && '*'}
                    </span>
                    {meta.build_num && ')'}
                    {' · started '}
                    {formatStartedAt(meta.started_at)}
                  </span>
                  {import.meta.env.DEV && (
                    <span
                      className="ml-1.5 inline-flex items-center rounded-md bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-900 ring-1 ring-inset ring-amber-500/30 dark:bg-amber-950/60 dark:text-amber-200"
                      title="Vite dev server is running with HMR — the frontend may not match the reported build SHA"
                    >
                      dev
                    </span>
                  )}
                </p>
              )}
              {usage?.guest_recipient && (
                <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
                  <span className="font-medium text-foreground">{usage.guest_recipient}</span>
                  {me && me.demo_mode && <LevelBadge level={me.level} />}
                </p>
              )}
              <div className="mt-1.5 flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => setShowHowItWorks(true)}
                  className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-2 py-0.5 text-xs font-medium text-muted-foreground shadow-sm hover:bg-accent hover:text-foreground"
                >
                  How it works
                </button>
                {showAdminLink && (
                  <a
                    href="#/advanced"
                    className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-2 py-0.5 text-xs font-medium text-muted-foreground shadow-sm hover:bg-accent hover:text-foreground"
                  >
                    Advanced <span aria-hidden>→</span>
                  </a>
                )}
              </div>
            </div>
            <button
              type="button"
              onClick={() => stackRef.current?.snapAll()}
              title="Snap widgets back to the corner"
              aria-label="Snap widgets back to the corner"
              className="-mr-1.5 shrink-0 rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              <PanelRightOpen className="h-4 w-4" />
            </button>
          </div>
        </header>

      {showHowItWorks && <HowItWorks onClose={() => setShowHowItWorks(false)} />}

      <main className="space-y-6 px-6 py-8 lg:pr-[19rem]">
        <form onSubmit={submit} className="space-y-3">
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Is double-teaming allowed?"
            rows={3}
            className="w-full resize-y rounded-md border border-input bg-card p-3 text-sm shadow-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                submit(e as unknown as React.FormEvent)
              }
            }}
          />
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-sm">
              <label htmlFor="sport" className="text-muted-foreground">
                Sport:
              </label>
              <select
                id="sport"
                value={sport}
                onChange={(e) => setSport(e.target.value)}
                className="rounded-md border border-input bg-card px-2 py-1 text-sm shadow-sm"
              >
                <option value="">All (compare across sports)</option>
                {(meta?.sports ?? []).map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
              <span className="text-xs text-muted-foreground">
                ⌘/Ctrl+Enter to submit
              </span>
            </div>
            <button
              type="submit"
              disabled={loading || !question.trim()}
              className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground shadow-sm hover:bg-primary/90 disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground"
            >
              {loading ? 'Thinking…' : 'Ask'}
            </button>
          </div>
        </form>

        {error && (
          <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
            <div className="font-medium">Request failed</div>
            <div className="mt-1 whitespace-pre-wrap font-mono text-xs">{error}</div>
          </div>
        )}

        {result && (
          <>
            <section className="rounded-md border border-border bg-card p-4 shadow-sm">
              <div className="mb-2 flex items-center justify-between text-xs uppercase tracking-wide text-muted-foreground">
                <span>Answer</span>
                <span className="font-mono normal-case text-muted-foreground">
                  {result.model}
                </span>
              </div>
              {result.stop_reason === 'max_tokens' && (
                <div
                  className="mb-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800"
                  title="Anthropic returned stop_reason=max_tokens — model was cut off mid-response"
                >
                  <span className="font-medium">Answer truncated —</span> the model hit the
                  output-token cap before finishing. The text below stops mid-thought.
                  Raise <span className="font-mono">max_tokens</span> in{' '}
                  <span className="font-mono">generate.py</span> and re-ask.
                </div>
              )}
              {result.stop_reason && result.stop_reason !== 'end_turn' && result.stop_reason !== 'max_tokens' && (
                <div className="mb-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                  Unexpected stop_reason:{' '}
                  <span className="font-mono">{result.stop_reason}</span>. The answer below
                  may be incomplete.
                </div>
              )}
              <div className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">
                {result.answer}
              </div>
              <div className="mt-3 text-xs text-muted-foreground">
                {result.input_tokens.toLocaleString()} in ·{' '}
                {result.output_tokens.toLocaleString()} out tokens
              </div>
              <div className="mt-4 border-t border-border pt-3">
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span>Rate this answer:</span>
                  {([1, 2, 3, 4, 5] as Rating[]).map((n) => {
                    const active = rating === n
                    return (
                      <button
                        key={n}
                        type="button"
                        onClick={() => sendFeedback(n, tags, comment)}
                        aria-pressed={active}
                        title={`${n} — ${RATING_LABELS[n]}`}
                        className={
                          'w-7 rounded border py-0.5 font-mono transition ' +
                          (active
                            ? 'border-primary bg-accent text-foreground'
                            : 'border-input hover:bg-accent')
                        }
                      >
                        {n}
                      </button>
                    )
                  })}
                  {rating != null && (
                    <span className="text-muted-foreground">
                      {RATING_LABELS[rating]}
                    </span>
                  )}
                  {ratingError && (
                    <span className="ml-auto text-destructive" title={ratingError}>
                      couldn't save
                    </span>
                  )}
                </div>
                {rating != null && canEvaluate && (
                  <div className="mt-3 space-y-2">
                    <div className="flex flex-wrap items-center gap-1.5 text-xs">
                      <span className="text-muted-foreground">Issue tags:</span>
                      {TAGS.map((t) => {
                        const active = tags.has(t)
                        return (
                          <button
                            key={t}
                            type="button"
                            onClick={() => toggleTag(t)}
                            aria-pressed={active}
                            title={TAG_LABELS[t]}
                            className={
                              'rounded-full border px-2 py-0.5 transition ' +
                              (active
                                ? 'border-primary bg-accent text-foreground'
                                : 'border-input text-muted-foreground hover:bg-accent hover:text-foreground')
                            }
                          >
                            {t}
                          </button>
                        )
                      })}
                    </div>
                    <textarea
                      value={comment}
                      onChange={(e) => setComment(e.target.value)}
                      placeholder="What stood out, good or bad? (optional)"
                      rows={2}
                      className="w-full resize-y rounded-md border border-input bg-card p-2 text-xs shadow-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
                    />
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-muted-foreground">
                        {comment !== savedComment
                          ? 'Unsaved changes to your note.'
                          : savedComment
                            ? 'Note saved.'
                            : 'Rating saved. A note about what worked or didn’t helps future review.'}
                      </span>
                      {comment !== savedComment && (
                        <button
                          type="button"
                          onClick={() => sendFeedback(rating, tags, comment)}
                          className="rounded-md bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground shadow-sm hover:bg-primary/90"
                        >
                          Save note
                        </button>
                      )}
                    </div>
                  </div>
                )}
              </div>
              {canEvaluate && (
              <div className="mt-4 border-t border-border pt-3">
                <label className="flex flex-wrap items-baseline gap-2 text-xs">
                  <span className="text-muted-foreground">Gold answer</span>
                  <span className="text-muted-foreground">
                    — edit the answer above into what a knowledgeable human would give.
                    Use <span className="font-mono">## Ultimate</span> /{' '}
                    <span className="font-mono">## Goaltimate</span> headings so each
                    section retrieves under its sport. Included in the index on the
                    next rebuild.
                  </span>
                </label>
                <textarea
                  value={gold}
                  onChange={(e) => setGold(e.target.value)}
                  placeholder="(seeded with the model's answer once one is generated)"
                  rows={10}
                  className="mt-2 w-full resize-y rounded-md border border-input bg-card p-2 font-mono text-xs shadow-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
                />
                <div className="mt-2 flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">
                    {goldError ? (
                      <span className="text-destructive" title={goldError}>
                        couldn't save
                      </span>
                    ) : gold === savedGold && savedGold ? (
                      'Gold saved. Rebuild the index to make it retrievable.'
                    ) : gold && gold !== savedGold ? (
                      'Unsaved edits.'
                    ) : (
                      'Optional. Rebuild command: uv run python scripts/build_index.py'
                    )}
                  </span>
                  {gold.trim() && gold !== savedGold && (
                    <button
                      type="button"
                      onClick={saveGold}
                      disabled={goldSaving}
                      className="rounded-md bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground shadow-sm hover:bg-primary/90 disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground"
                    >
                      {goldSaving ? 'Saving…' : 'Save gold answer'}
                    </button>
                  )}
                </div>
              </div>
              )}
            </section>

            <section className="overflow-hidden rounded-md border border-border bg-card shadow-sm">
              <button
                type="button"
                onClick={() => setSourcesOpen(!sourcesOpen)}
                className="flex w-full items-center justify-between px-4 py-3 text-sm font-medium hover:bg-accent"
              >
                <span>
                  {sourcesOpen ? '▼' : '▶'} Retrieved passages ({result.chunks.length})
                </span>
                <span className="text-xs font-normal text-muted-foreground">
                  the passages the model drew from above
                </span>
              </button>
              {sourcesOpen && (
                <div className="divide-y divide-border border-t border-border">
                  {result.chunks.map((c, i) => (
                    <ChunkRow key={i} chunk={c} />
                  ))}
                </div>
              )}
            </section>
          </>
        )}
      </main>

      {meta && (
        <footer className="px-6 py-4 text-xs text-muted-foreground lg:pr-[19rem]">
          embeddings: {meta.embedding_provider}/{meta.embedding_model} · gen:{' '}
          {meta.claude_model}
        </footer>
      )}
      <FloatingWidgetStack<WidgetCtx>
        ref={stackRef}
        widgets={widgets}
        ctx={widgetCtx}
      />
      </div>
    </LayoutProvider>
  )
}

function ChunkRow({ chunk }: { chunk: Chunk }) {
  // Gold chunks have no meaningful page (both 0); hide the pages label
  // rather than showing "p.0", matching the backend citation formatter.
  const pages =
    chunk.page_start === 0 && chunk.page_end === 0
      ? ''
      : chunk.page_start === chunk.page_end
        ? `p.${chunk.page_start}`
        : `pp.${chunk.page_start}-${chunk.page_end}`
  return (
    <div className="p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
        <span className="rounded bg-secondary px-2 py-0.5 font-mono text-secondary-foreground">
          {chunk.sport}
        </span>
        <span className="font-mono text-foreground">{chunk.rule_id}</span>
        <span className="text-muted-foreground">{pages}</span>
        <span className="ml-auto font-mono text-muted-foreground" title="L2 distance on unit vectors; lower = more similar">
          d={chunk.distance.toFixed(3)}
        </span>
      </div>
      <div className="whitespace-pre-wrap text-xs leading-relaxed text-foreground">
        {chunk.text}
      </div>
    </div>
  )
}
