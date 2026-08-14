/**
 * Usage widget — surfaces the llm-guardrails CostCounter snapshot.
 *
 * Exports:
 *   UsageSummaryLine — one-line status shown in the widget header
 *                      (compact spend/cap for the most-actionable window).
 *   UsageBody        — expanded panel body with all three windows,
 *                      cap bars, and enforcement state.
 *
 * Data comes from GET /usage (backed by CostCounter.snapshot_for).
 * The parent component fetches and passes the snapshot in via props
 * — this file only renders.
 */

import { Info } from 'lucide-react'

export interface UsageSnapshot {
  hourly_usd: number
  daily_usd: number
  weekly_usd: number
  caps: {
    hourly_usd: number
    daily_usd: number
    weekly_usd: number
    per_token_usd: number
  }
  caller_weekly_usd: number | null
  guardrails_enabled: boolean
  per_provider_usd: Record<string, number>
  guest_recipient: string | null
}

function pct(n: number, d: number): number {
  return d > 0 ? Math.min(100, (n / d) * 100) : 0
}

function money(n: number): string {
  return n < 0.01 ? '<$0.01' : `$${n.toFixed(2)}`
}

// Per-provider totals are often sub-cent for Voyage embeddings, so
// two-decimal `money()` collapses everything to "<$0.01" and loses the
// signal. This variant keeps four decimals in the sub-cent range so
// $0.0001 and $0.006 render distinctly.
function moneyPrecise(n: number): string {
  if (n === 0) return '$0.00'
  if (n < 0.0001) return '<$0.0001'
  if (n < 0.01) return `$${n.toFixed(4)}`
  return `$${n.toFixed(2)}`
}

export function UsageSummaryLine({ usage }: { usage: UsageSnapshot | null }) {
  if (!usage)
    return (
      <span className="text-[11px] font-medium">
        Usage <span className="text-muted-foreground">…</span>
      </span>
    )
  const p = pct(usage.daily_usd, usage.caps.daily_usd)
  return (
    <span className="flex items-center gap-1.5 text-[11px] font-medium">
      <span>Usage</span>
      <span className="font-mono font-semibold tabular-nums text-emerald-600 dark:text-emerald-400">
        {money(usage.daily_usd)}
      </span>
      <span className="text-muted-foreground">/ {money(usage.caps.daily_usd)} today</span>
      <span
        className={
          'ml-auto text-[10px] font-medium ' +
          (p >= 100 ? 'text-red-600' : p >= 80 ? 'text-amber-600' : 'text-muted-foreground')
        }
      >
        {p.toFixed(0)}%
      </span>
    </span>
  )
}

function CapBar({
  label,
  info,
  spent,
  cap,
}: {
  label: string
  info: string
  spent: number
  cap: number
}) {
  const p = pct(spent, cap)
  return (
    <div className="space-y-0.5">
      <div className="flex items-baseline justify-between text-[11px]">
        <span className="flex items-center gap-0.5 text-muted-foreground">
          {label}
          <Info className="h-3 w-3 opacity-60" aria-label={info}>
            <title>{info}</title>
          </Info>
        </span>
        <span className="font-mono tabular-nums">
          <span className="text-emerald-600 dark:text-emerald-400">{money(spent)}</span>{' '}
          <span className="text-muted-foreground">/ {money(cap)}</span>
        </span>
      </div>
      <div className="h-1 overflow-hidden rounded-full bg-border">
        <div
          className={
            'h-full transition-all ' +
            (p >= 100 ? 'bg-red-500' : p >= 80 ? 'bg-amber-500' : 'bg-emerald-500')
          }
          style={{ width: `${p}%` }}
        />
      </div>
    </div>
  )
}

export function UsageBody({ usage }: { usage: UsageSnapshot | null }) {
  if (!usage) return <div className="p-2 text-xs text-muted-foreground">Loading…</div>
  return (
    <div className="space-y-2.5 p-2 text-xs">
      {/* Your own per-guest spend first — most users only care about theirs. */}
      {usage.caller_weekly_usd != null && (
        <div>
          <div className="mb-1.5 text-[11px] text-muted-foreground">you · this week</div>
          <CapBar
            label="you"
            info={`Your week · ${money(usage.caps.per_token_usd)} per-guest cap`}
            spent={usage.caller_weekly_usd}
            cap={usage.caps.per_token_usd}
          />
        </div>
      )}
      {/* The three deployment-wide guardrails — spend across all guests. */}
      <div className={usage.caller_weekly_usd != null ? 'border-t border-border pt-2' : undefined}>
        <div className="mb-1.5 text-[11px] text-muted-foreground">all guests · deployment caps</div>
        <div className="space-y-2.5">
          <CapBar
            label="hour"
            info={`All guests · ${money(usage.caps.hourly_usd)} cap · resets hourly`}
            spent={usage.hourly_usd}
            cap={usage.caps.hourly_usd}
          />
          <CapBar
            label="day"
            info={`All guests · ${money(usage.caps.daily_usd)} cap · resets 00:00 UTC`}
            spent={usage.daily_usd}
            cap={usage.caps.daily_usd}
          />
          <CapBar
            label="week"
            info={`All guests · ${money(usage.caps.weekly_usd)} cap · resets Mon`}
            spent={usage.weekly_usd}
            cap={usage.caps.weekly_usd}
          />
        </div>
      </div>
      {Object.keys(usage.per_provider_usd).length > 0 && (
        <div className="space-y-0.5 border-t border-border pt-2 text-[11px]">
          <div className="flex items-center gap-0.5 text-muted-foreground">
            by provider
            <Info
              className="h-3 w-3 opacity-60"
              aria-label="In-memory USD totals per provider since server start. Resets on restart."
            >
              <title>In-memory USD totals per provider since server start. Resets on restart.</title>
            </Info>
          </div>
          {Object.entries(usage.per_provider_usd)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([provider, usd]) => (
              <div key={provider} className="flex items-baseline justify-between pl-3">
                <span className="text-muted-foreground">{provider}</span>
                <span className="font-mono tabular-nums text-emerald-600 dark:text-emerald-400">
                  {moneyPrecise(usd)}
                </span>
              </div>
            ))}
        </div>
      )}
      {!usage.guardrails_enabled && (
        <div
          className="text-[10px] text-amber-700"
          title="GUARDRAILS_ENABLED=false in .env — caps track spend but don't block calls."
        >
          <span className="rounded bg-amber-100 px-1 py-0.5 font-medium">off</span>
          <span className="ml-1 text-muted-foreground">not enforcing</span>
        </div>
      )}
    </div>
  )
}
