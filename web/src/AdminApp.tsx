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

  useEffect(() => {
    void refresh()
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

  const includedCount = rows?.filter((r) => r.included).length ?? 0
  const totalCount = rows?.length ?? 0

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
                Curate user-authored gold answers. Excluded rows are skipped by the next index rebuild.
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

        {rows === null && !error && (
          <div className="text-sm text-slate-500">Loading…</div>
        )}

        {rows !== null && rows.length === 0 && (
          <div className="rounded-md border border-slate-200 bg-white p-6 text-sm text-slate-500 shadow-sm">
            No gold answers yet. Rate an answer in the main app and use the "Save gold answer" button.
          </div>
        )}

        {rows !== null && rows.length > 0 && (
          <>
            <div className="flex items-center justify-between gap-3 text-xs text-slate-500">
              <span>
                <span className="font-medium text-slate-700">{includedCount}</span> of{' '}
                <span className="font-medium text-slate-700">{totalCount}</span> golds included in
                next rebuild
              </span>
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
      </main>
    </div>
  )
}
