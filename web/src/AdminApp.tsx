import { Fragment, useEffect, useState } from 'react'

// Admin surface for grooming user-authored gold answers before the next
// index rebuild. Deliberately kept small: this is a curator's workflow,
// not a casual-user surface. Reached via URL hash `#/admin` — see main.tsx.

interface AdminGoldRow {
  qa_id: string
  question: string
  gold_answer: string
  timestamp: string
  included: boolean
}

interface AdminGoldListResponse {
  golds: AdminGoldRow[]
}

interface RebuildResult {
  ok: boolean
  duration_seconds: number
  stdout_tail: string
  stderr_tail: string
}

interface AdminSourceRow {
  path: string
  sport: string
  size_bytes: number
  modified_at: string
  included: boolean
}

interface AdminSourceListResponse {
  sources: AdminSourceRow[]
}

interface AdminFeedbackRow {
  qa_id: string
  timestamp: string
  rating: number
  tags: string[]
  comment: string | null
  question: string
  has_gold: boolean
}

interface AdminFeedbackListResponse {
  feedback: AdminFeedbackRow[]
}

type AdminTab = 'feedback' | 'golds' | 'sources'

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function formatWhen(iso: string): string {
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

export default function AdminApp() {
  const [rows, setRows] = useState<AdminGoldRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set())
  const [pending, setPending] = useState<Set<string>>(() => new Set())
  const [rebuilding, setRebuilding] = useState(false)
  const [rebuildResult, setRebuildResult] = useState<RebuildResult | null>(null)
  // Single-editor policy: only one row's gold_answer can be edited at a
  // time. Clicking "Edit" on another row discards the in-flight buffer.
  const [editingQaId, setEditingQaId] = useState<string | null>(null)
  const [editBuffer, setEditBuffer] = useState('')
  const [savingEdit, setSavingEdit] = useState(false)
  const [editError, setEditError] = useState<string | null>(null)
  // Sources tab state
  const [activeTab, setActiveTab] = useState<AdminTab>('feedback')
  const [sources, setSources] = useState<AdminSourceRow[] | null>(null)
  const [sourcePending, setSourcePending] = useState<Set<string>>(() => new Set())
  const [feedback, setFeedback] = useState<AdminFeedbackRow[] | null>(null)

  useEffect(() => {
    void refresh()
    void refreshSources()
    void refreshFeedback()
  }, [])

  async function refresh() {
    setError(null)
    try {
      const resp = await fetch('/admin/golds')
      if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`)
      const data: AdminGoldListResponse = await resp.json()
      setRows(data.golds)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  async function refreshFeedback() {
    try {
      const resp = await fetch('/admin/feedback')
      if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`)
      const data: AdminFeedbackListResponse = await resp.json()
      setFeedback(data.feedback)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  async function refreshSources() {
    try {
      const resp = await fetch('/admin/sources')
      if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`)
      const data: AdminSourceListResponse = await resp.json()
      setSources(data.sources)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  async function toggleSourceInclusion(row: AdminSourceRow) {
    const next = !row.included
    setSources((prev) =>
      prev?.map((r) => (r.path === row.path ? { ...r, included: next } : r)) ?? prev,
    )
    setSourcePending((prev) => new Set(prev).add(row.path))
    try {
      const resp = await fetch('/admin/source-curation', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ path: row.path, included: next }),
      })
      if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`)
    } catch (err) {
      setSources((prev) =>
        prev?.map((r) => (r.path === row.path ? { ...r, included: row.included } : r))
          ?? prev,
      )
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSourcePending((prev) => {
        const next = new Set(prev)
        next.delete(row.path)
        return next
      })
    }
  }

  async function toggleInclusion(row: AdminGoldRow) {
    const next = !row.included
    // Optimistic — reflect the change immediately, revert if the POST fails.
    setRows((prev) =>
      prev?.map((r) => (r.qa_id === row.qa_id ? { ...r, included: next } : r)) ?? prev,
    )
    setPending((prev) => new Set(prev).add(row.qa_id))
    try {
      const resp = await fetch('/admin/gold-curation', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ qa_id: row.qa_id, included: next }),
      })
      if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`)
    } catch (err) {
      // Revert optimistic change.
      setRows((prev) =>
        prev?.map((r) => (r.qa_id === row.qa_id ? { ...r, included: row.included } : r))
          ?? prev,
      )
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setPending((prev) => {
        const next = new Set(prev)
        next.delete(row.qa_id)
        return next
      })
    }
  }

  async function rebuildIndex() {
    if (rebuilding) return
    setRebuilding(true)
    setRebuildResult(null)
    try {
      const resp = await fetch('/admin/rebuild-index', { method: 'POST' })
      if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`)
      const data: RebuildResult = await resp.json()
      setRebuildResult(data)
      // A rebuild may have picked up new files added on disk since page load.
      void refreshSources()
    } catch (err) {
      setRebuildResult({
        ok: false,
        duration_seconds: 0,
        stdout_tail: '',
        stderr_tail: err instanceof Error ? err.message : String(err),
      })
    } finally {
      setRebuilding(false)
    }
  }

  function beginEdit(row: AdminGoldRow) {
    setEditingQaId(row.qa_id)
    setEditBuffer(row.gold_answer)
    setEditError(null)
    // Auto-expand so the edit box is visible in the same row.
    setExpanded((prev) => {
      const next = new Set(prev)
      next.add(row.qa_id)
      return next
    })
  }

  function cancelEdit() {
    setEditingQaId(null)
    setEditBuffer('')
    setEditError(null)
  }

  async function saveEdit(row: AdminGoldRow) {
    if (savingEdit) return
    if (!editBuffer.trim()) {
      setEditError('Gold answer cannot be empty.')
      return
    }
    setSavingEdit(true)
    setEditError(null)
    try {
      const resp = await fetch('/gold', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          qa_id: row.qa_id,
          question: row.question,
          gold_answer: editBuffer,
        }),
      })
      if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`)
      // Reflect the edit locally with a fresh timestamp so the "SAVED"
      // column updates immediately.
      const newIso = new Date().toISOString()
      setRows((prev) =>
        prev?.map((r) =>
          r.qa_id === row.qa_id
            ? { ...r, gold_answer: editBuffer, timestamp: newIso }
            : r,
        ) ?? prev,
      )
      setEditingQaId(null)
      setEditBuffer('')
    } catch (err) {
      setEditError(err instanceof Error ? err.message : String(err))
    } finally {
      setSavingEdit(false)
    }
  }

  function toggleExpanded(qa_id: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(qa_id)) next.delete(qa_id)
      else next.add(qa_id)
      return next
    })
  }

  const goldIncluded = rows?.filter((r) => r.included).length ?? 0
  const goldTotal = rows?.length ?? 0
  const sourceIncluded = sources?.filter((s) => s.included).length ?? 0
  const sourceTotal = sources?.length ?? 0
  // "Needs attention" = rated 3 or lower, no gold saved yet. That's the
  // subset a curator would actually work through.
  const feedbackNeedsAttention =
    feedback?.filter((f) => f.rating <= 3 && !f.has_gold).length ?? 0
  const feedbackTotal = feedback?.length ?? 0

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-5xl px-6 py-4">
          <div className="flex items-baseline justify-between gap-4">
            <div>
              <h1 className="text-xl font-semibold tracking-tight">
                Rulebook <span className="text-slate-400">/ admin</span>
              </h1>
              <p className="text-sm text-slate-500">
                Curate gold answers and source files. Excluded rows are skipped by the next index rebuild.
              </p>
            </div>
            <a href="#/" className="text-sm text-blue-600 hover:underline">
              ← back to Q&amp;A
            </a>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl space-y-4 px-6 py-6">
        {error && (
          <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            <div className="font-medium">Request failed</div>
            <div className="mt-1 whitespace-pre-wrap font-mono text-xs">{error}</div>
          </div>
        )}

        {/* Rebuild control — global, applies to whichever tab is active. */}
        <div className="flex items-center justify-end">
          <button
            type="button"
            onClick={rebuildIndex}
            disabled={rebuilding}
            title="Runs scripts/build_index.py — typically 15s, occasionally up to a minute or two when Voyage is slow"
            className="rounded-md bg-blue-600 px-3 py-1 text-xs font-medium text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            {rebuilding ? 'Rebuilding…' : 'Rebuild index'}
          </button>
        </div>
        {rebuildResult && (
          <div
            className={
              'rounded-md border p-3 text-xs ' +
              (rebuildResult.ok
                ? 'border-green-300 bg-green-50 text-green-900'
                : 'border-red-300 bg-red-50 text-red-900')
            }
          >
            <div className="mb-1 font-medium">
              {rebuildResult.ok
                ? `Rebuilt in ${rebuildResult.duration_seconds}s`
                : 'Rebuild failed'}
            </div>
            <pre className="whitespace-pre-wrap font-mono text-[11px] leading-snug">
              {rebuildResult.ok ? rebuildResult.stdout_tail : rebuildResult.stderr_tail}
            </pre>
          </div>
        )}

        {/* Tab bar — counts baked into labels so both are visible regardless of active tab. */}
        <div className="flex gap-1 border-b border-slate-200 text-sm">
          {(['feedback', 'golds', 'sources'] as AdminTab[]).map((t) => {
            const active = activeTab === t
            const label =
              t === 'feedback'
                ? `Feedback (${feedbackNeedsAttention} to review · ${feedbackTotal})`
                : t === 'golds'
                  ? `Golds (${goldIncluded}/${goldTotal})`
                  : `Sources (${sourceIncluded}/${sourceTotal})`
            return (
              <button
                key={t}
                type="button"
                onClick={() => setActiveTab(t)}
                className={
                  '-mb-px border-b-2 px-3 py-1.5 font-medium transition ' +
                  (active
                    ? 'border-blue-600 text-blue-700'
                    : 'border-transparent text-slate-500 hover:text-slate-700')
                }
              >
                {label}
              </button>
            )
          })}
        </div>

        {activeTab === 'feedback' && feedback === null && !error && (
          <div className="text-sm text-slate-500">Loading feedback…</div>
        )}
        {activeTab === 'feedback' && feedback !== null && feedback.length === 0 && (
          <div className="rounded-md border border-slate-200 bg-white p-6 text-sm text-slate-500 shadow-sm">
            No feedback yet. Rate some answers in the main app.
          </div>
        )}
        {activeTab === 'feedback' && feedback !== null && feedback.length > 0 && (
          <section className="overflow-hidden rounded-md border border-slate-200 bg-white shadow-sm">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="w-16 px-3 py-2 text-center">rating</th>
                  <th className="w-16 px-3 py-2 text-center" title="Whether a gold answer has been saved for this qa_id">
                    gold
                  </th>
                  <th className="px-3 py-2">question / note</th>
                  <th className="w-40 px-3 py-2">tags</th>
                  <th className="w-40 px-3 py-2">when</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {feedback.map((f) => {
                  const needsAttention = f.rating <= 3 && !f.has_gold
                  return (
                    <tr
                      key={f.qa_id + '-' + f.timestamp}
                      className={needsAttention ? 'bg-amber-50 hover:bg-amber-100' : 'hover:bg-slate-50'}
                    >
                      <td className="px-3 py-2 text-center">
                        <span
                          className={
                            'inline-flex h-6 w-6 items-center justify-center rounded-full font-mono text-xs ' +
                            (f.rating <= 2
                              ? 'bg-red-100 text-red-700'
                              : f.rating === 3
                                ? 'bg-amber-100 text-amber-700'
                                : 'bg-green-100 text-green-700')
                          }
                          title={
                            f.rating <= 2
                              ? 'wrong / mostly wrong'
                              : f.rating === 3
                                ? 'mixed / missing key nuance'
                                : 'mostly right / perfect'
                          }
                        >
                          {f.rating}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-center">
                        {f.has_gold ? (
                          <span title="Gold answer authored" className="text-green-600">✓</span>
                        ) : (
                          <span title="No gold yet" className="text-slate-300">·</span>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <div className="text-sm text-slate-800">
                          {f.question || <span className="italic text-slate-400">(no qa_log entry)</span>}
                        </div>
                        {f.comment && (
                          <div className="mt-1 whitespace-pre-wrap text-xs text-slate-500">
                            {f.comment}
                          </div>
                        )}
                        <div className="mt-1 font-mono text-[10px] text-slate-400">
                          {f.qa_id.slice(0, 8)}
                        </div>
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex flex-wrap gap-1">
                          {f.tags.length === 0 ? (
                            <span className="text-xs text-slate-400">—</span>
                          ) : (
                            f.tags.map((t) => (
                              <span
                                key={t}
                                className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-700"
                              >
                                {t}
                              </span>
                            ))
                          )}
                        </div>
                      </td>
                      <td className="px-3 py-2 text-xs text-slate-500">
                        {formatWhen(f.timestamp)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </section>
        )}

        {activeTab === 'golds' && rows === null && !error && (
          <div className="text-sm text-slate-500">Loading golds…</div>
        )}
        {activeTab === 'golds' && rows !== null && rows.length === 0 && (
          <div className="rounded-md border border-slate-200 bg-white p-6 text-sm text-slate-500 shadow-sm">
            No gold answers yet. Rate an answer in the main app and use the "Save gold answer" button.
          </div>
        )}
        {activeTab === 'golds' && rows !== null && rows.length > 0 && (
          <>
            <section className="overflow-hidden rounded-md border border-slate-200 bg-white shadow-sm">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="w-16 px-3 py-2">incl.</th>
                    <th className="px-3 py-2">question</th>
                    <th className="w-40 px-3 py-2">saved</th>
                    <th className="w-24 px-3 py-2">qa_id</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {rows.map((r) => (
                    <Fragment key={r.qa_id}>
                      <tr className="hover:bg-slate-50">
                        <td className="px-3 py-2">
                          <button
                            type="button"
                            onClick={() => toggleInclusion(r)}
                            disabled={pending.has(r.qa_id)}
                            aria-pressed={r.included}
                            title={r.included ? 'Included — click to exclude' : 'Excluded — click to include'}
                            className={
                              'inline-flex h-5 w-9 items-center rounded-full border transition ' +
                              (r.included
                                ? 'border-green-500 bg-green-500 justify-end'
                                : 'border-slate-300 bg-slate-200 justify-start') +
                              (pending.has(r.qa_id) ? ' opacity-50' : '')
                            }
                          >
                            <span className="mx-0.5 h-4 w-4 rounded-full bg-white shadow-sm" />
                          </button>
                        </td>
                        <td className="px-3 py-2">
                          <button
                            type="button"
                            onClick={() => toggleExpanded(r.qa_id)}
                            className="text-left text-sm text-slate-800 hover:text-blue-600"
                          >
                            {expanded.has(r.qa_id) ? '▼' : '▶'} {r.question}
                          </button>
                        </td>
                        <td className="px-3 py-2 text-xs text-slate-500">
                          {formatWhen(r.timestamp)}
                        </td>
                        <td className="px-3 py-2 font-mono text-xs text-slate-400">
                          {r.qa_id.slice(0, 8)}
                        </td>
                      </tr>
                      {expanded.has(r.qa_id) && (
                        <tr className="bg-slate-50">
                          <td />
                          <td colSpan={3} className="px-3 py-3">
                            {editingQaId === r.qa_id ? (
                              <div className="space-y-2">
                                <textarea
                                  value={editBuffer}
                                  onChange={(e) => setEditBuffer(e.target.value)}
                                  rows={12}
                                  className="w-full resize-y rounded-md border border-slate-300 bg-white p-2 font-mono text-xs shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                                />
                                <div className="flex items-center justify-between gap-3 text-xs">
                                  <span className="text-slate-400">
                                    Saves a new row to gold.jsonl. Rebuild index to make it retrievable.
                                    {editError && (
                                      <span className="ml-2 text-red-600">{editError}</span>
                                    )}
                                  </span>
                                  <span className="flex gap-2">
                                    <button
                                      type="button"
                                      onClick={cancelEdit}
                                      disabled={savingEdit}
                                      className="rounded-md border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                                    >
                                      Cancel
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => saveEdit(r)}
                                      disabled={savingEdit || !editBuffer.trim() || editBuffer === r.gold_answer}
                                      className="rounded-md bg-slate-700 px-2.5 py-1 text-xs font-medium text-white shadow-sm hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
                                    >
                                      {savingEdit ? 'Saving…' : 'Save'}
                                    </button>
                                  </span>
                                </div>
                              </div>
                            ) : (
                              <div className="space-y-2">
                                <pre className="whitespace-pre-wrap font-mono text-xs leading-relaxed text-slate-700">
                                  {r.gold_answer}
                                </pre>
                                <div className="flex justify-end">
                                  <button
                                    type="button"
                                    onClick={() => beginEdit(r)}
                                    className="rounded-md border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50"
                                  >
                                    Edit
                                  </button>
                                </div>
                              </div>
                            )}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </section>
          </>
        )}

        {activeTab === 'sources' && sources === null && !error && (
          <div className="text-sm text-slate-500">Loading sources…</div>
        )}
        {activeTab === 'sources' && sources !== null && sources.length === 0 && (
          <div className="rounded-md border border-slate-200 bg-white p-6 text-sm text-slate-500 shadow-sm">
            No source files found under <span className="font-mono">rules/&lt;sport&gt;/</span>.
          </div>
        )}
        {activeTab === 'sources' && sources !== null && sources.length > 0 && (
          <section className="overflow-hidden rounded-md border border-slate-200 bg-white shadow-sm">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="w-16 px-3 py-2">incl.</th>
                  <th className="w-28 px-3 py-2">sport</th>
                  <th className="px-3 py-2">path</th>
                  <th className="w-24 px-3 py-2 text-right">size</th>
                  <th className="w-40 px-3 py-2">modified</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {sources.map((s) => (
                  <tr key={s.path} className="hover:bg-slate-50">
                    <td className="px-3 py-2">
                      <button
                        type="button"
                        onClick={() => toggleSourceInclusion(s)}
                        disabled={sourcePending.has(s.path)}
                        aria-pressed={s.included}
                        title={s.included ? 'Included — click to exclude' : 'Excluded — click to include'}
                        className={
                          'inline-flex h-5 w-9 items-center rounded-full border transition ' +
                          (s.included
                            ? 'border-green-500 bg-green-500 justify-end'
                            : 'border-slate-300 bg-slate-200 justify-start') +
                          (sourcePending.has(s.path) ? ' opacity-50' : '')
                        }
                      >
                        <span className="mx-0.5 h-4 w-4 rounded-full bg-white shadow-sm" />
                      </button>
                    </td>
                    <td className="px-3 py-2">
                      <span className="rounded bg-slate-100 px-2 py-0.5 font-mono text-xs text-slate-700">
                        {s.sport}
                      </span>
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-slate-700">
                      {s.path}
                    </td>
                    <td className="px-3 py-2 text-right text-xs text-slate-500">
                      {formatBytes(s.size_bytes)}
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-500">
                      {formatWhen(s.modified_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}
      </main>
    </div>
  )
}
