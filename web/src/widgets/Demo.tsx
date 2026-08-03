/**
 * Demo widget — placeholder.
 *
 * In a sibling app this shows invite-recipient context (greeting,
 * per-invite spend caps). Rulebook doesn't have guest-auth yet, so
 * this widget renders a placeholder until that lands and we can fill
 * it in with real content.
 *
 * The shape is here so the widget slot exists in the stack — once
 * guest-auth is adopted, replace this file's body with the real
 * greeting + per-guest usage line.
 */

export function DemoSummaryLine() {
  return <span className="text-muted-foreground">not yet available</span>
}

export function DemoBody() {
  return (
    <div className="space-y-2 p-2 text-[11px] text-muted-foreground">
      <p>
        Waiting on <span className="font-mono">guest-auth</span> adoption.
      </p>
      <p>
        Will show your greeting and per-guest weekly spend once you're identified
        by an invite link.
      </p>
    </div>
  )
}
