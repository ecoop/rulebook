// Formatting shared by the Users and Requests tabs.

// Compact "3d ago" style for the Users tab's last-seen column.
export function fmtRelative(iso: string | null): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '—'
  const secs = Math.max(0, (Date.now() - then) / 1000)
  if (secs < 60) return 'now'
  const mins = secs / 60
  if (mins < 60) return `${Math.floor(mins)}m`
  const hrs = mins / 60
  if (hrs < 24) return `${Math.floor(hrs)}h`
  const days = hrs / 24
  if (days < 30) return `${Math.floor(days)}d`
  return `${Math.floor(days / 30)}mo`
}

// The shareable invite URL for a token — what an admin actually wants to copy.
// The `name` param is ignored by the server (only `token` is read); it's a
// sanity check so the sender can eyeball whose link they're about to send.
export function inviteLinkFor(token: string, label: string): string {
  return `${window.location.origin}/?token=${token}&name=${encodeURIComponent(label)}`
}
