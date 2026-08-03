/**
 * Diagnostics widget — live runtime stats.
 *
 * Shows the state of the index, HITL corpus, and source registry at a
 * glance. Backed by GET /diagnostics.
 */

import { Info } from 'lucide-react'

export interface DiagnosticsSnapshot {
  chunk_count: number
  dimension: number
  chunks_by_sport: Record<string, number>
  index_built_at: string | null
  gold_count: number
  feedback_count: number
  source_file_count: number
}

function formatWhen(iso: string | null): string {
  if (!iso) return 'never built'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function DiagnosticsSummaryLine({ diag }: { diag: DiagnosticsSnapshot | null }) {
  if (!diag) return <span className="text-muted-foreground">…</span>
  return (
    <span className="flex items-center gap-1.5">
      <span className="font-mono tabular-nums">{diag.chunk_count.toLocaleString()}</span>
      <span className="text-muted-foreground">chunks · {diag.dimension}d</span>
    </span>
  )
}

function Row({
  label,
  info,
  value,
  indent = false,
}: {
  label: string
  info?: string
  value: React.ReactNode
  indent?: boolean
}) {
  return (
    <div className={'flex items-baseline justify-between ' + (indent ? 'pl-3' : '')}>
      <span className="flex items-center gap-0.5 text-muted-foreground">
        {label}
        {info && (
          <Info className="h-3 w-3 opacity-60" aria-label={info}>
            <title>{info}</title>
          </Info>
        )}
      </span>
      <span className="font-mono tabular-nums text-foreground">{value}</span>
    </div>
  )
}

export function DiagnosticsBody({ diag }: { diag: DiagnosticsSnapshot | null }) {
  if (!diag) return <div className="p-2 text-xs text-muted-foreground">Loading…</div>
  const bySport = Object.entries(diag.chunks_by_sport).sort(([a], [b]) => a.localeCompare(b))
  return (
    <div className="space-y-2 p-2 text-[11px]">
      <div className="space-y-1">
        <Row
          label="chunks"
          info="Total embedded rows in the current vector index."
          value={diag.chunk_count.toLocaleString()}
        />
        {bySport.map(([sport, n]) => (
          <Row key={sport} label={sport} value={n.toLocaleString()} indent />
        ))}
        <Row
          label="dim"
          info="Embedding vector dimensionality (fixed per model)."
          value={diag.dimension}
        />
        <Row
          label="built"
          info="Local time the current index was last written."
          value={formatWhen(diag.index_built_at)}
        />
      </div>
      <div className="space-y-1 border-t border-border pt-2">
        <Row
          label="sources"
          info="Ingestable files under rules/<sport>/ (PDF, .md, .txt). Skips PDFs that have a .extracted.md sibling."
          value={diag.source_file_count}
        />
        <Row
          label="golds"
          info="Distinct qa_ids with a user-authored canonical answer."
          value={diag.gold_count}
        />
        <Row
          label="feedback"
          info="Distinct qa_ids that received any rating."
          value={diag.feedback_count}
        />
      </div>
    </div>
  )
}
