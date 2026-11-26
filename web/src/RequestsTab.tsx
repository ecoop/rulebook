// Requests tab (#337): join requests from people without an invite, plus the
// live join settings. Approve creates the user (same path as Add invitee);
// decline keeps the record for audit; purge (superuser) deletes declined ones.
// The parent owns the fetch so the tab label can show the waiting count.

import { useEffect, useState } from 'react'
import { levelInfo } from './levels'
import { fmtRelative, inviteLinkFor } from './userFormat'

export interface JoinRequestOut {
  id: string
  name: string
  email: string
  heard_about: string
  created_at: string
  source: string
  referred_by: string | null
  status: 'pending' | 'approved' | 'declined'
  decided_at: string | null
  decided_by: string | null
  invite_token: string | null
  granted_role: string | null
  granted_domains: string[] | null
}

export interface JoinSettingsOut {
  mode: string
  pending_cap: number
  default_role: string
  default_domains: string[]
  updated_at: string | null
  updated_by: string | null
  modes: string[]
  accepting_public: boolean
  email_configured: boolean
}

export interface JoinRequestsResponse {
  requests: JoinRequestOut[]
  pending: number
  settings: JoinSettingsOut
}

const INPUT =
  'rounded-md border border-input bg-card px-2 py-1 text-xs shadow-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50'
const SECONDARY =
  'rounded-md border border-input bg-card px-2.5 py-1 text-xs font-medium text-foreground hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50'
const PRIMARY =
  'rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground shadow-sm hover:bg-primary/90 disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground'

function chipClass(on: boolean): string {
  return (
    'rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors disabled:opacity-50 ' +
    (on
      ? 'border-foreground bg-foreground text-background'
      : 'border-border text-muted-foreground hover:bg-accent hover:text-foreground')
  )
}

function DomainToggles({
  all,
  built,
  value,
  disabled,
  onChange,
}: {
  all: string[]
  built: string[]
  value: Set<string>
  disabled?: boolean
  onChange: (next: Set<string>) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {all.map((s) => {
        const on = value.has(s)
        return (
          <button
            key={s}
            type="button"
            aria-pressed={on}
            disabled={disabled}
            onClick={() => {
              const next = new Set(value)
              if (on) next.delete(s)
              else next.add(s)
              onChange(next)
            }}
            title={built.includes(s) ? undefined : 'Not indexed yet'}
            className={chipClass(on)}
          >
            {s}
            {built.includes(s) ? '' : ' ·'}
          </button>
        )
      })}
    </div>
  )
}

function RoleSelect({
  ladder,
  value,
  disabled,
  onChange,
}: {
  ladder: string[]
  value: string
  disabled?: boolean
  onChange: (role: string) => void
}) {
  return (
    <select value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)} className={INPUT}>
      {ladder.map((r, i) =>
        r === 'suspended' ? null : (
          <option key={r} value={r}>
            {levelInfo(i).name}
          </option>
        ),
      )}
    </select>
  )
}

async function call(url: string, init?: RequestInit): Promise<Response> {
  const resp = await fetch(url, init)
  if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`)
  return resp
}

const JSON_HEADERS = { 'content-type': 'application/json' }

function ago(iso: string | null): string {
  const r = fmtRelative(iso)
  return r === '—' ? r : r === 'now' ? 'just now' : `${r} ago`
}

// ── Join settings card ──────────────────────────────────────────────────────

function SettingsCard({
  settings,
  ladder,
  allDomains,
  builtDomains,
  canConfigure,
  onSaved,
  onError,
}: {
  settings: JoinSettingsOut
  ladder: string[]
  allDomains: string[]
  builtDomains: string[]
  canConfigure: boolean
  onSaved: () => Promise<void>
  onError: (msg: string | null) => void
}) {
  const [mode, setMode] = useState(settings.mode)
  const [cap, setCap] = useState(String(settings.pending_cap))
  const [role, setRole] = useState(settings.default_role)
  const [domains, setDomains] = useState<Set<string>>(() => new Set(settings.default_domains))
  const [saving, setSaving] = useState(false)
  const [testMsg, setTestMsg] = useState<string | null>(null)

  // Re-seed from the server whenever it changes (after a save or a refresh).
  useEffect(() => {
    setMode(settings.mode)
    setCap(String(settings.pending_cap))
    setRole(settings.default_role)
    setDomains(new Set(settings.default_domains))
  }, [settings])

  const capNum = Number(cap)
  const orderedDomains = allDomains.filter((d) => domains.has(d))
  const dirty =
    mode !== settings.mode ||
    capNum !== settings.pending_cap ||
    role !== settings.default_role ||
    orderedDomains.join(',') !== allDomains.filter((d) => settings.default_domains.includes(d)).join(',')
  const valid = Number.isInteger(capNum) && capNum >= 1 && capNum <= 100 && orderedDomains.length > 0

  async function save() {
    setSaving(true)
    onError(null)
    try {
      await call('/advanced/join-settings', {
        method: 'PUT',
        headers: JSON_HEADERS,
        body: JSON.stringify({ mode, pending_cap: capNum, default_role: role, default_domains: orderedDomains }),
      })
      await onSaved()
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  async function sendTest() {
    setTestMsg('Sending…')
    try {
      const resp = await call('/advanced/join-settings/test-email', { method: 'POST' })
      setTestMsg(`Sent to ${(await resp.json()).to}`)
    } catch (err) {
      setTestMsg(err instanceof Error ? err.message : String(err))
    }
  }

  const ro = !canConfigure || saving
  return (
    <section className="space-y-3 rounded-md border border-border bg-card p-4 text-sm shadow-sm">
      <div className="text-xs font-medium text-muted-foreground">Join settings</div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="w-28 text-xs text-muted-foreground">Requests</span>
        {settings.modes.map((m) => (
          <button
            key={m}
            type="button"
            aria-pressed={mode === m}
            disabled={ro}
            onClick={() => setMode(m)}
            className={chipClass(mode === m)}
          >
            {m}
          </button>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="w-28 text-xs text-muted-foreground">Close at</span>
        <input
          type="number"
          min={1}
          max={100}
          value={cap}
          disabled={ro}
          onChange={(e) => setCap(e.target.value)}
          className={INPUT + ' w-16'}
        />
        <span className="text-xs text-muted-foreground">waiting (public requests only)</span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="w-28 text-xs text-muted-foreground">Approve as</span>
        <RoleSelect ladder={ladder} value={role} disabled={ro} onChange={setRole} />
        <DomainToggles all={allDomains} built={builtDomains} value={domains} disabled={ro} onChange={setDomains} />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="w-28 text-xs text-muted-foreground">Email</span>
        <span className="text-xs text-foreground">
          {settings.email_configured ? 'on' : 'off (not configured)'}
        </span>
        {canConfigure && settings.email_configured && (
          <button type="button" onClick={() => void sendTest()} className={SECONDARY}>
            Send test
          </button>
        )}
        {testMsg && <span className="text-xs text-muted-foreground">{testMsg}</span>}
        <span className="flex-1" />
        {canConfigure && (
          <button type="button" disabled={!dirty || !valid || saving} onClick={() => void save()} className={PRIMARY}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        )}
      </div>
      {settings.updated_at && (
        <div className="text-xs text-muted-foreground">
          Last changed {ago(settings.updated_at)}{settings.updated_by ? ` by ${settings.updated_by}` : ''}.
        </div>
      )}
    </section>
  )
}

// ── One waiting request ─────────────────────────────────────────────────────

function PendingRequest({
  req,
  settings,
  ladder,
  allDomains,
  builtDomains,
  canDecide,
  onDecided,
  onError,
}: {
  req: JoinRequestOut
  settings: JoinSettingsOut
  ladder: string[]
  allDomains: string[]
  builtDomains: string[]
  canDecide: boolean
  onDecided: (approved?: { token: string; label: string }) => Promise<void>
  onError: (msg: string | null) => void
}) {
  const [label, setLabel] = useState(req.name)
  const [role, setRole] = useState(settings.default_role)
  const [domains, setDomains] = useState<Set<string>>(() => new Set(settings.default_domains))
  const [busy, setBusy] = useState(false)

  async function approve() {
    setBusy(true)
    onError(null)
    try {
      const resp = await call(`/advanced/join-requests/${encodeURIComponent(req.id)}/approve`, {
        method: 'POST',
        headers: JSON_HEADERS,
        body: JSON.stringify({ label: label.trim(), role, domains: allDomains.filter((d) => domains.has(d)) }),
      })
      const body = await resp.json()
      await onDecided({ token: body.token, label: body.label })
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err))
      setBusy(false)
    }
  }

  async function decline() {
    if (!window.confirm(`Decline ${req.name}'s request? They aren't told; the record is kept until purged.`)) return
    setBusy(true)
    onError(null)
    try {
      await call(`/advanced/join-requests/${encodeURIComponent(req.id)}/decline`, { method: 'POST' })
      await onDecided()
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err))
      setBusy(false)
    }
  }

  const ro = !canDecide || busy
  return (
    <div className={'space-y-2 px-4 py-3' + (busy ? ' opacity-50' : '')}>
      <div className="text-sm text-foreground">
        <span className="font-medium">{req.name}</span>
        <span className="text-muted-foreground"> · {req.email} · {ago(req.created_at)}</span>
        {req.source !== 'web' && <span className="text-muted-foreground"> · {req.source}</span>}
        {req.referred_by && <span className="text-muted-foreground"> · referred by {req.referred_by}</span>}
      </div>
      <div className="text-sm text-muted-foreground">“{req.heard_about}”</div>
      {canDecide && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">Label</span>
          <input
            type="text"
            value={label}
            disabled={ro}
            onChange={(e) => setLabel(e.target.value)}
            className={INPUT + ' w-40'}
          />
          <span className="text-xs text-muted-foreground">Role</span>
          <RoleSelect ladder={ladder} value={role} disabled={ro} onChange={setRole} />
          <span className="text-xs text-muted-foreground">Domains</span>
          <DomainToggles all={allDomains} built={builtDomains} value={domains} disabled={ro} onChange={setDomains} />
          <span className="flex-1" />
          <button type="button" disabled={ro} onClick={() => void decline()} className={SECONDARY}>
            Decline
          </button>
          <button
            type="button"
            disabled={ro || !label.trim() || domains.size === 0}
            onClick={() => void approve()}
            className={PRIMARY}
          >
            {busy ? 'Working…' : 'Approve'}
          </button>
        </div>
      )}
    </div>
  )
}

// ── The tab ─────────────────────────────────────────────────────────────────

export function RequestsTab({
  data,
  can,
  ladder,
  allDomains,
  builtDomains,
  refresh,
  onUsersChanged,
}: {
  data: JoinRequestsResponse | null
  can: (cap: string) => boolean
  ladder: string[]
  allDomains: string[]
  builtDomains: string[]
  refresh: () => Promise<void>
  onUsersChanged: () => void
}) {
  const [error, setError] = useState<string | null>(null)
  const [approved, setApproved] = useState<{ token: string; label: string } | null>(null)
  const [copied, setCopied] = useState(false)
  const [purging, setPurging] = useState(false)

  if (data === null) return <div className="text-sm text-muted-foreground">Loading requests…</div>

  const waiting = data.requests.filter((r) => r.status === 'pending')
  const decided = data.requests.filter((r) => r.status !== 'pending')
  const declinedCount = decided.filter((r) => r.status === 'declined').length

  async function onDecided(a?: { token: string; label: string }) {
    if (a) {
      setApproved(a)
      setCopied(false)
      onUsersChanged()
    }
    await refresh()
  }

  async function purge() {
    if (
      !window.confirm(
        `Permanently delete ${declinedCount} declined request${declinedCount === 1 ? '' : 's'}, including names and emails? This can't be undone.`,
      )
    )
      return
    setPurging(true)
    setError(null)
    try {
      await call('/advanced/join-requests/purge', { method: 'POST' })
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setPurging(false)
    }
  }

  const link = approved ? inviteLinkFor(approved.token, approved.label) : null
  return (
    <div className="space-y-4">
      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          <div className="font-medium">Request failed</div>
          <div className="mt-1 whitespace-pre-wrap font-mono text-xs">{error}</div>
        </div>
      )}

      <SettingsCard
        settings={data.settings}
        ladder={ladder}
        allDomains={allDomains}
        builtDomains={builtDomains}
        canConfigure={can('requests.configure')}
        onSaved={refresh}
        onError={setError}
      />

      {approved && link && (
        <div className="rounded-md border border-green-300 bg-green-50 p-3 text-xs text-green-900">
          <div className="mb-1 font-medium">Approved {approved.label}. Share this invite link:</div>
          <div className="flex items-center gap-2">
            <code className="flex-1 truncate rounded bg-card px-2 py-1 font-mono text-[11px] text-foreground">
              {link}
            </code>
            <button
              type="button"
              onClick={() => {
                void navigator.clipboard.writeText(link).then(() => setCopied(true), () => {})
              }}
              className="rounded-md border border-green-300 bg-card px-2 py-1 font-medium text-green-800 hover:bg-green-100"
            >
              {copied ? 'Copied' : 'Copy link'}
            </button>
          </div>
        </div>
      )}

      <section className="rounded-md border border-border bg-card shadow-sm">
        <div className="border-b border-border px-4 py-2 text-xs font-medium text-muted-foreground">
          Waiting ({waiting.length})
        </div>
        {waiting.length === 0 ? (
          <div className="px-4 py-3 text-sm text-muted-foreground">No requests waiting.</div>
        ) : (
          <div className="divide-y divide-border">
            {waiting.map((r) => (
              <PendingRequest
                key={r.id}
                req={r}
                settings={data.settings}
                ladder={ladder}
                allDomains={allDomains}
                builtDomains={builtDomains}
                canDecide={can('requests.decide')}
                onDecided={onDecided}
                onError={setError}
              />
            ))}
          </div>
        )}
      </section>

      <section className="w-full overflow-x-auto rounded-md border border-border bg-card shadow-sm">
        <div className="flex items-center border-b border-border px-4 py-2 text-xs font-medium text-muted-foreground">
          <span className="flex-1">Decided ({decided.length})</span>
          {can('requests.purge') && (
            <button
              type="button"
              disabled={declinedCount === 0 || purging}
              onClick={() => void purge()}
              className={SECONDARY}
            >
              {purging ? 'Purging…' : `Purge declined (${declinedCount})…`}
            </button>
          )}
        </div>
        {decided.length === 0 ? (
          <div className="px-4 py-3 text-sm text-muted-foreground">Nothing decided yet.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-muted text-left text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-3 py-2">name</th>
                <th className="px-3 py-2">email</th>
                <th className="px-3 py-2">status</th>
                <th className="px-3 py-2">decided</th>
                <th className="px-3 py-2">by</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {decided.map((r) => (
                <tr key={r.id} className="hover:bg-accent">
                  <td className="whitespace-nowrap px-3 py-2 text-foreground">{r.name}</td>
                  <td className="px-3 py-2 text-muted-foreground">{r.email}</td>
                  <td className="px-3 py-2 text-foreground">{r.status}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                    {ago(r.decided_at)}
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">{r.decided_by ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}
