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
}

type Rating = 1 | 2 | 3 | 4 | 5

const RATING_LABELS: Record<Rating, string> = {
  1: 'very wrong',
  2: 'mostly wrong',
  3: 'mixed / missing key nuance',
  4: 'mostly right',
  5: 'perfect',
}

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
  // Rating + comment state is scoped to the *current* result — clearing on
  // new submissions so a prior vote never bleeds onto a new answer.
  const [rating, setRating] = useState<Rating | null>(null)
  const [comment, setComment] = useState('')
  // The comment "state" we last successfully sent. Used to compute whether
  // there are unsent edits so the Save-note button can hide when there's
  // nothing to save.
  const [savedComment, setSavedComment] = useState('')
  const [ratingError, setRatingError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/meta')
      .then((r) => (r.ok ? r.json() : Promise.reject(r.statusText)))
      .then(setMeta)
      .catch(() => {
        // Non-fatal — the app is still usable, we just won't populate the
        // sport dropdown from the server's view.
      })
  }, [])

  async function sendFeedback(nextRating: Rating, commentToSend: string) {
    if (!result) return
    // Optimistic: reflect the click immediately, revert on error. This is
    // a low-stakes personal-tool interaction — the fast feedback is worth
    // more than waiting for the network round-trip.
    const previousRating = rating
    const previousSavedComment = savedComment
    setRating(nextRating)
    setSavedComment(commentToSend)
    setRatingError(null)
    try {
      const resp = await fetch('/feedback', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          qa_id: result.qa_id,
          rating: nextRating,
          comment: commentToSend.trim() ? commentToSend : null,
        }),
      })
      if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`)
    } catch (err) {
      setRating(previousRating)
      setSavedComment(previousSavedComment)
      setRatingError(err instanceof Error ? err.message : String(err))
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!question.trim() || loading) return
    setLoading(true)
    setError(null)
    setResult(null)
    setRating(null)
    setComment('')
    setSavedComment('')
    setRatingError(null)
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
          <h1 className="text-xl font-semibold tracking-tight">ulty-goalty</h1>
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
                        onClick={() => sendFeedback(n, comment)}
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
                  <div className="mt-2 space-y-2">
                    <textarea
                      value={comment}
                      onChange={(e) => setComment(e.target.value)}
                      placeholder="What was missing or wrong? (optional)"
                      rows={2}
                      className="w-full resize-y rounded-md border border-slate-300 bg-white p-2 text-xs shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    />
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-slate-400">
                        Rating saved automatically. Note saves when you click below.
                      </span>
                      {comment !== savedComment && (
                        <button
                          type="button"
                          onClick={() => sendFeedback(rating, comment)}
                          className="rounded-md bg-slate-700 px-2.5 py-1 text-xs font-medium text-white shadow-sm hover:bg-slate-800"
                        >
                          Save note
                        </button>
                      )}
                    </div>
                  </div>
                )}
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
