import { useEffect, useState } from 'react'

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
  retrieval: 'wrong sources retrieved — retrieval quality issue',
  format: 'facts right, delivery off — prompt tuning',
}

const TAGS: IssueTag[] = ['wrong', 'incomplete', 'retrieval', 'format']

interface Meta {
  sports: string[]
  embedding_provider: string
  embedding_model: string
  claude_model: string
  build_sha: string
  build_dirty: boolean
  started_at: string
}

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

  useEffect(() => {
    fetch('/meta')
      .then((r) => (r.ok ? r.json() : Promise.reject(r.statusText)))
      .then(setMeta)
      .catch(() => {
        // Non-fatal — the app is still usable, we just won't populate the
        // sport dropdown from the server's view.
      })
  }, [])

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
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-4xl px-6 py-4">
          <h1 className="text-xl font-semibold tracking-tight">Rulebook</h1>
          <p className="text-sm text-slate-500">
            Ask about the rules of ultimate and goaltimate. Answers cite the actual rule numbers.
          </p>
        </div>
      </header>

      <main className="mx-auto max-w-4xl space-y-6 px-6 py-8">
        <form onSubmit={submit} className="space-y-3">
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Is double-teaming allowed?"
            rows={3}
            className="w-full resize-y rounded-md border border-slate-300 bg-white p-3 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                submit(e as unknown as React.FormEvent)
              }
            }}
          />
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-sm">
              <label htmlFor="sport" className="text-slate-600">
                Sport:
              </label>
              <select
                id="sport"
                value={sport}
                onChange={(e) => setSport(e.target.value)}
                className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm shadow-sm"
              >
                <option value="">All (compare across sports)</option>
                {(meta?.sports ?? []).map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
              <span className="text-xs text-slate-400">
                ⌘/Ctrl+Enter to submit
              </span>
            </div>
            <button
              type="submit"
              disabled={loading || !question.trim()}
              className="rounded-md bg-blue-600 px-4 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              {loading ? 'Thinking…' : 'Ask'}
            </button>
          </div>
        </form>

        {error && (
          <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            <div className="font-medium">Request failed</div>
            <div className="mt-1 whitespace-pre-wrap font-mono text-xs">{error}</div>
          </div>
        )}

        {result && (
          <>
            <section className="rounded-md border border-slate-200 bg-white p-4 shadow-sm">
              <div className="mb-2 flex items-center justify-between text-xs uppercase tracking-wide text-slate-500">
                <span>Answer</span>
                <span className="font-mono normal-case text-slate-400">
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
              <div className="whitespace-pre-wrap text-sm leading-relaxed text-slate-800">
                {result.answer}
              </div>
              <div className="mt-3 text-xs text-slate-400">
                {result.input_tokens.toLocaleString()} in ·{' '}
                {result.output_tokens.toLocaleString()} out tokens
              </div>
              <div className="mt-4 border-t border-slate-100 pt-3">
                <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
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
                            ? 'border-blue-500 bg-blue-50 text-blue-700'
                            : 'border-slate-300 hover:bg-slate-50')
                        }
                      >
                        {n}
                      </button>
                    )
                  })}
                  {rating != null && (
                    <span className="text-slate-400">
                      {RATING_LABELS[rating]}
                    </span>
                  )}
                  {ratingError && (
                    <span className="ml-auto text-red-600" title={ratingError}>
                      couldn't save
                    </span>
                  )}
                </div>
                {rating != null && (
                  <div className="mt-3 space-y-2">
                    <div className="flex flex-wrap items-center gap-1.5 text-xs">
                      <span className="text-slate-500">Issue tags:</span>
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
                                ? 'border-blue-500 bg-blue-50 text-blue-700'
                                : 'border-slate-300 text-slate-600 hover:bg-slate-50')
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
                      className="w-full resize-y rounded-md border border-slate-300 bg-white p-2 text-xs shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    />
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-slate-400">
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
                          className="rounded-md bg-slate-700 px-2.5 py-1 text-xs font-medium text-white shadow-sm hover:bg-slate-800"
                        >
                          Save note
                        </button>
                      )}
                    </div>
                  </div>
                )}
              </div>
              <div className="mt-4 border-t border-slate-100 pt-3">
                <label className="flex flex-wrap items-baseline gap-2 text-xs">
                  <span className="text-slate-500">Gold answer</span>
                  <span className="text-slate-400">
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
                  className="mt-2 w-full resize-y rounded-md border border-slate-300 bg-white p-2 font-mono text-xs shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
                <div className="mt-2 flex items-center justify-between text-xs">
                  <span className="text-slate-400">
                    {goldError ? (
                      <span className="text-red-600" title={goldError}>
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
                      className="rounded-md bg-slate-700 px-2.5 py-1 text-xs font-medium text-white shadow-sm hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
                    >
                      {goldSaving ? 'Saving…' : 'Save gold answer'}
                    </button>
                  )}
                </div>
              </div>
            </section>

            <section className="overflow-hidden rounded-md border border-slate-200 bg-white shadow-sm">
              <button
                type="button"
                onClick={() => setSourcesOpen(!sourcesOpen)}
                className="flex w-full items-center justify-between px-4 py-3 text-sm font-medium hover:bg-slate-50"
              >
                <span>
                  {sourcesOpen ? '▼' : '▶'} Retrieved sources ({result.chunks.length})
                </span>
                <span className="text-xs font-normal text-slate-400">
                  these chunks fed the model above
                </span>
              </button>
              {sourcesOpen && (
                <div className="divide-y divide-slate-100 border-t border-slate-100">
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
        <footer className="mx-auto max-w-4xl px-6 py-4 text-xs text-slate-400">
          embeddings: {meta.embedding_provider}/{meta.embedding_model} · gen:{' '}
          {meta.claude_model} · build{' '}
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
          </span>{' '}
          · started {formatStartedAt(meta.started_at)}
          {import.meta.env.DEV && (
            <span
              className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 font-medium text-amber-800"
              title="Vite dev server is running with HMR — the frontend may not match the reported build SHA"
            >
              dev
            </span>
          )}
          <span className="mx-2 text-slate-300">·</span>
          <a href="#/admin" className="text-slate-500 hover:text-blue-600 hover:underline">
            admin
          </a>
        </footer>
      )}
    </div>
  )
}

function ChunkRow({ chunk }: { chunk: Chunk }) {
  const pages =
    chunk.page_start === chunk.page_end
      ? `p.${chunk.page_start}`
      : `pp.${chunk.page_start}-${chunk.page_end}`
  return (
    <div className="p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
        <span className="rounded bg-blue-100 px-2 py-0.5 font-mono text-blue-800">
          {chunk.sport}
        </span>
        <span className="font-mono text-slate-700">{chunk.rule_id}</span>
        <span className="text-slate-400">{pages}</span>
        <span className="ml-auto font-mono text-slate-400" title="L2 distance on unit vectors; lower = more similar">
          d={chunk.distance.toFixed(3)}
        </span>
      </div>
      <div className="whitespace-pre-wrap text-xs leading-relaxed text-slate-700">
        {chunk.text}
      </div>
    </div>
  )
}
