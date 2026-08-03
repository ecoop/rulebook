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
}

function pct(n: number, d: number): number {
  return d > 0 ? Math.min(100, (n / d) * 100) : 0
}

function money(n: number): string {
  return n < 0.01 ? '<$0.01' : `$${n.toFixed(2)}`
}

export function UsageSummaryLine({ usage }: { usage: UsageSnapshot | null }) {
  if (!usage) return <span className="text-muted-foreground">…</span>
  const p = pct(usage.daily_usd, usage.caps.daily_usd)
  return (
    <span className="flex items-center gap-1.5">
      <span className="font-mono tabular-nums">{money(usage.daily_usd)}</span>
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
          {money(spent)} <span className="text-muted-foreground">/ {money(cap)}</span>
        </span>
      </div>
      <div className="h-1 overflow-hidden rounded-full bg-border">
        <div
          className={
            'h-full transition-all ' +
            (p >= 100 ? 'bg-red-500' : p >= 80 ? 'bg-amber-500' : 'bg-blue-500')
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
      <CapBar
        label="hour"
        info="USD spent on LLM calls in the current UTC hour. Resets at :00."
        spent={usage.hourly_usd}
        cap={usage.caps.hourly_usd}
      />
      <CapBar
        label="day"
        info="USD spent today (UTC). Resets at midnight UTC."
        spent={usage.daily_usd}
        cap={usage.caps.daily_usd}
      />
      <CapBar
        label="week"
        info="USD spent this week (UTC, Mon-based). Resets Monday 00:00 UTC."
        spent={usage.weekly_usd}
        cap={usage.caps.weekly_usd}
      />
      {!usage.guardrails_enabled && (
        <div
          className="text-[10px] text-amber-700"
          title="GUARDRAILS_ENABLED=false in .env — caps track spend but don't block calls."
        >
          <span className="rounded bg-amber-100 px-1 py-0.5 font-medium">off</span>
          <span className="ml-1 text-muted-foreground">not enforcing</span>
        </div>
      )}
      {usage.caller_weekly_usd != null && (
        <div className="border-t border-border pt-2 text-[11px]">
          <div className="flex items-baseline justify-between">
            <span className="flex items-center gap-0.5 text-muted-foreground">
              you
              <Info
                className="h-3 w-3 opacity-60"
                aria-label="Your cumulative weekly spend against the per-guest cap. Populates when guest-auth identifies you."
              >
                <title>Your cumulative weekly spend against the per-guest cap.</title>
              </Info>
            </span>
            <span className="font-mono tabular-nums">
              {money(usage.caller_weekly_usd)}{' '}
              <span className="text-muted-foreground">
                / {money(usage.caps.per_token_usd)}
              </span>
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
