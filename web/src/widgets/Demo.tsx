/**
 * Demo widget — guest-auth greeting + per-guest weekly spend.
 *
 * Reads the same UsageSnapshot the Usage widget consumes (already
 * carries guest_recipient + caller_weekly_usd) rather than fetching a
 * separate endpoint. When demo_mode is off (guest_recipient=null),
 * renders a "not signed in" note explaining the widget is dormant.
 */

import type { UsageSnapshot } from './Usage'

function money(n: number): string {
  return n < 0.01 ? '<$0.01' : `$${n.toFixed(2)}`
}

export function DemoSummaryLine({ usage }: { usage: UsageSnapshot | null }) {
  if (!usage) return <span className="text-muted-foreground">…</span>
  if (!usage.guest_recipient) {
    return <span className="text-muted-foreground">not signed in</span>
  }
  return <span className="truncate">{usage.guest_recipient}</span>
}

export function DemoBody({ usage }: { usage: UsageSnapshot | null }) {
  if (!usage) return <div className="p-2 text-xs text-muted-foreground">Loading…</div>

  if (!usage.guest_recipient) {
    return (
      <div className="space-y-2 p-2 text-[11px] text-muted-foreground">
        <p>Not signed in with an invite.</p>
        <p>
          When <span className="font-mono">RULEBOOK_DEMO_MODE=true</span> and a
          valid <span className="font-mono">?token=</span> link is used, this
          widget shows your greeting and per-guest weekly spend.
        </p>
      </div>
    )
  }

  const spent = usage.caller_weekly_usd ?? 0
  const cap = usage.caps.per_token_usd
  const pct = cap > 0 ? Math.min(100, (spent / cap) * 100) : 0
  return (
    <div className="space-y-2 p-2 text-[11px]">
      <div>
        <div className="text-muted-foreground">signed in as</div>
        <div className="text-sm font-medium text-foreground">{usage.guest_recipient}</div>
      </div>
      <div className="space-y-0.5 border-t border-border pt-2">
        <div className="flex items-baseline justify-between">
          <span className="text-muted-foreground">your week</span>
          <span className="font-mono tabular-nums">
            {money(spent)} <span className="text-muted-foreground">/ {money(cap)}</span>
          </span>
        </div>
        <div className="h-1 overflow-hidden rounded-full bg-border">
          <div
            className={
              'h-full transition-all ' +
              (pct >= 100 ? 'bg-red-500' : pct >= 80 ? 'bg-amber-500' : 'bg-blue-500')
            }
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
    </div>
  )
}
