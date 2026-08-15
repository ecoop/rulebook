import { Fragment, useEffect, useState } from 'react'
import { LevelBadge, levelInfo, levelNumber } from './levels'

// Advanced surface — capability-gated tabs (feedback / golds / sources / users
// / audit) for reviewers, operators, and admins. Reached via URL hash
// `#/advanced` — see main.tsx.

interface AdminGoldRow {
  gold_id: string
  qa_id: string
  question: string
  gold_answer: string
  author: string | null
  is_own: boolean
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

interface IndexBuild {
  build_id: string | null
  built_at: string | null
  git_sha: string | null
  build_num: string | null
  count: number
  sources: { sport: string; file: string }[]
  gold_answers: number
  gold_chunks: number
  golds: { gold_id: string | null; author: string | null; question: string }[]
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

// --- Users tab (superuser) — invite allowlist × role assignments ------------
interface MeResponse {
  recipient: string | null
  role: string
  level: number
  capabilities: string[]
  demo_mode: boolean
}

interface AuditRow {
  timestamp: string
  actor: string | null
  action: string
  target: string | null
  detail: Record<string, unknown>
}

interface InviteTokenOut {
  token: string
  label: string
  last_seen: string | null
  weekly_usd: number
  weekly_tokens: number
  questions: number
  comments: number
  golds: number
}

interface InviteTokensResponse {
  tokens: InviteTokenOut[]
}

interface RoleAssignmentOut {
  token: string
  role: string
  source: string
}

interface AdminRolesResponse {
  roles: RoleAssignmentOut[]
  ladder: string[]
}

// One row per invite token, joined with its effective role + engagement.
interface UserRow {
  token: string
  label: string
  role: string
  source: string
  lastSeen: string | null
  weeklyUsd: number
  weeklyTokens: number
  questions: number
  comments: number
  golds: number
}

type AdminTab = 'feedback' | 'golds' | 'sources' | 'indices' | 'users' | 'audit'

type SortDir = 'asc' | 'desc'
type FeedbackSortCol = 'rating' | 'has_gold' | 'timestamp'
type SourceSortCol = 'included' | 'sport' | 'path' | 'size_bytes' | 'modified_at'
type UserSortCol = 'label' | 'role' | 'lastSeen' | 'questions' | 'golds' | 'weeklyTokens'

const USER_SORT_KEY = 'rulebook.usersSort'
const USER_SORT_COLS: readonly UserSortCol[] = [
  'label', 'role', 'lastSeen', 'questions', 'golds', 'weeklyTokens',
]

// Restore the persisted Users-tab sort, validating against current columns so
// a stale/removed column (or a private-mode read error) falls back cleanly.
function loadUserSort(): { col: UserSortCol; dir: SortDir } {
  try {
    const p = JSON.parse(localStorage.getItem(USER_SORT_KEY) ?? '')
    if ((USER_SORT_COLS as readonly string[]).includes(p?.col) && (p?.dir === 'asc' || p?.dir === 'desc')) {
      return { col: p.col, dir: p.dir }
    }
  } catch {
    /* no/invalid stored value — use the default */
  }
  return { col: 'label', dir: 'asc' }
}

// Compact "3d ago" style for the Users tab's last-seen column.
function fmtRelative(iso: string | null): string {
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

function fmtMoney(n: number): string {
  if (n <= 0) return '$0'
  return n < 0.01 ? '<$0.01' : `$${n.toFixed(2)}`
}

function fmtTokens(n: number): string {
  if (!n) return '0'
  if (n < 1000) return String(n)
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}k`
  return `${(n / 1_000_000).toFixed(1)}M`
}

// "$0.03 · 1.2k" — combined weekly spend + tokens; em-dash when idle.
function fmtEngagement(usd: number, tokens: number): string {
  if (!usd && !tokens) return '—'
  return `${fmtMoney(usd)} · ${fmtTokens(tokens)} tok`
}

// The shareable invite URL for a token — what an admin actually wants to copy.
// The `name` param is ignored by the server (only `token` is read); it's a
// sanity check so the sender can eyeball whose link they're about to send.
function inviteLinkFor(token: string, label: string): string {
  return `${window.location.origin}/?token=${token}&name=${encodeURIComponent(label)}`
}

// Logical role ordering (low→high) — numbered levels (docs/rbac-capabilities.md
// §4), a fallback when the backend ladder from GET /advanced/roles hasn't loaded.
const ROLE_LADDER_FALLBACK = [
  'level0', 'level1', 'level2', 'level3', 'level4',
  'level5', 'level6', 'level7', 'level8',
]

// Generic click handler for a sortable table column: same column → flip
// direction, new column → default to ascending. Keeps the per-table sort
// state inline (below) without a shared reducer.
function nextSort<C extends string>(
  current: { col: C; dir: SortDir },
  col: C,
): { col: C; dir: SortDir } {
  if (current.col === col) return { col, dir: current.dir === 'asc' ? 'desc' : 'asc' }
  return { col, dir: 'asc' }
}

function sortIndicator(active: boolean, dir: SortDir): string {
  if (!active) return ''
  return dir === 'asc' ? ' ▲' : ' ▼'
}

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

export default function AdvancedApp() {
  const [rows, setRows] = useState<AdminGoldRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set())
  const [pending, setPending] = useState<Set<string>>(() => new Set())
  const [rebuilding, setRebuilding] = useState(false)
  const [rebuildResult, setRebuildResult] = useState<RebuildResult | null>(null)
  const [indexBuilds, setIndexBuilds] = useState<IndexBuild[] | null>(null)
  const [activeBuildId, setActiveBuildId] = useState<string | null>(null)
  const [expandedBuild, setExpandedBuild] = useState<string | null>(null)
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
  const [audit, setAudit] = useState<AuditRow[] | null>(null)
  // Sort state per table. Defaults chosen to match the backend's natural
  // return order so a first render doesn't reshuffle.
  const [feedbackSort, setFeedbackSort] = useState<{ col: FeedbackSortCol; dir: SortDir }>({
    col: 'timestamp',
    dir: 'desc',
  })
  const [sourceSort, setSourceSort] = useState<{ col: SourceSortCol; dir: SortDir }>({
    col: 'sport',
    dir: 'asc',
  })
  // Users-tab sort persists across visits (localStorage) — handy in review
  // mode where you keep coming back to the same sort.
  const [userSort, setUserSort] = useState<{ col: UserSortCol; dir: SortDir }>(() =>
    loadUserSort(),
  )
  useEffect(() => {
    try {
      localStorage.setItem(USER_SORT_KEY, JSON.stringify(userSort))
    } catch {
      /* storage unavailable (private mode / quota) — non-fatal */
    }
  }, [userSort])
  // Users tab (superuser). `me` powers tab visibility; the table joins the
  // invite allowlist with role assignments.
  const [me, setMe] = useState<MeResponse | null>(null)
  const [meForbidden, setMeForbidden] = useState(false)
  const [inviteTokens, setInviteTokens] = useState<InviteTokenOut[] | null>(null)
  const [roles, setRoles] = useState<RoleAssignmentOut[] | null>(null)
  const [ladder, setLadder] = useState<string[]>([])
  const [addLabel, setAddLabel] = useState('')
  const [addPending, setAddPending] = useState(false)
  const [newInvite, setNewInvite] = useState<InviteTokenOut | null>(null)
  const [userPending, setUserPending] = useState<Set<string>>(() => new Set())
  const [copied, setCopied] = useState<string | null>(null)
  // Inline name (label) editing — one row at a time. `editingToken` is the row
  // being renamed; `editName` is the working buffer.
  const [editingToken, setEditingToken] = useState<string | null>(null)
  const [editName, setEditName] = useState('')

  // Everything is gated by CAPABILITY, not rank (docs/rbac-capabilities.md §6):
  // the UI renders a control iff /me's capability bundle grants it, and the
  // backend enforces the same. `activity.view` (level 1+) opens the page at all —
  // it's the personal "Your activity" surface; the operator tabs layer on top by
  // their own caps (advanced.view, *.view.all, curate, users, …).
  const caps = me?.capabilities ?? []
  const can = (c: string) => caps.includes(c)
  const canUseActivity = !!me && can('activity.view')

  useEffect(() => {
    void refreshMe()
  }, [])

  // Fetch each dataset only if the caller's capabilities grant that tab —
  // avoids 403 banners on tabs the role can't see.
  useEffect(() => {
    if (!canUseActivity) return
    if (can('golds.view')) void refresh()
    if (can('sources.view')) void refreshSources()
    if (can('feedback.view')) void refreshFeedback()
    if (can('users.view')) void refreshUsers()
    if (can('attribution.view')) void refreshAudit()
    if (can('index.rebuild')) void refreshIndexBuilds()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canUseActivity, caps.join(',')])

  async function refresh() {
    setError(null)
    try {
      const resp = await fetch('/advanced/golds')
      if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`)
      const data: AdminGoldListResponse = await resp.json()
      setRows(data.golds)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  async function refreshFeedback() {
    try {
      const resp = await fetch('/advanced/feedback')
      if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`)
      const data: AdminFeedbackListResponse = await resp.json()
      setFeedback(data.feedback)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  async function refreshAudit() {
    try {
      const resp = await fetch('/advanced/audit')
      if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`)
      const data: { audit: AuditRow[] } = await resp.json()
      setAudit(data.audit)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  async function refreshMe() {
    // /me is gated at novice, so a 403 means the guest is suspended — show
    // the suspended screen rather than the admin surface.
    try {
      const resp = await fetch('/me')
      if (resp.status === 403) {
        setMeForbidden(true)
        return
      }
      if (!resp.ok) return
      setMe(await resp.json())
    } catch {
      /* ignore — page renders its "checking access" state */
    }
  }

  async function refreshUsers() {
    try {
      const [tResp, rResp] = await Promise.all([
        fetch('/advanced/invite-tokens'),
        fetch('/advanced/roles'),
      ])
      if (!tResp.ok) throw new Error(`invite-tokens ${tResp.status}: ${await tResp.text()}`)
      if (!rResp.ok) throw new Error(`roles ${rResp.status}: ${await rResp.text()}`)
      const t: InviteTokensResponse = await tResp.json()
      const r: AdminRolesResponse = await rResp.json()
      setInviteTokens(t.tokens)
      setRoles(r.roles)
      setLadder(r.ladder)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  async function addUser() {
    const label = addLabel.trim()
    if (!label || addPending) return
    setAddPending(true)
    setError(null)
    setNewInvite(null)
    try {
      const resp = await fetch('/advanced/invite-tokens', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ label }),
      })
      if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`)
      setNewInvite((await resp.json()) as InviteTokenOut)
      setAddLabel('')
      await refreshUsers()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setAddPending(false)
    }
  }

  function markPending(token: string, on: boolean) {
    setUserPending((prev) => {
      const next = new Set(prev)
      if (on) next.add(token)
      else next.delete(token)
      return next
    })
  }

  async function changeRole(token: string, role: string) {
    markPending(token, true)
    setError(null)
    try {
      const resp = await fetch('/advanced/roles', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ token, role }),
      })
      if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`)
      await refreshUsers()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      markPending(token, false)
    }
  }

  function beginRename(token: string, label: string) {
    setEditingToken(token)
    setEditName(label)
  }

  function cancelRename() {
    setEditingToken(null)
    setEditName('')
  }

  async function renameUser(token: string, currentLabel: string) {
    const label = editName.trim()
    // No-op if unchanged or empty — just close the editor.
    if (!label || label === currentLabel) {
      cancelRename()
      return
    }
    markPending(token, true)
    setError(null)
    try {
      const resp = await fetch(`/advanced/invite-tokens/${encodeURIComponent(token)}`, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ label }),
      })
      if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`)
      cancelRename()
      await refreshUsers()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      markPending(token, false)
    }
  }

  async function resetRole(token: string) {
    markPending(token, true)
    setError(null)
    try {
      const resp = await fetch(`/advanced/roles/${encodeURIComponent(token)}/reset`, {
        method: 'POST',
      })
      if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`)
      await refreshUsers()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      markPending(token, false)
    }
  }

  async function removeUser(token: string, label: string) {
    // Nudge toward the reversible option — Suspend keeps audit; Remove is a
    // hard delete of the invite.
    if (
      !window.confirm(
        `Remove "${label}"? This hard-deletes their invite token and they can no longer sign in.\n\nFor a reversible block, cancel and set their role to "suspended" instead.`,
      )
    )
      return
    markPending(token, true)
    setError(null)
    try {
      const resp = await fetch(`/advanced/invite-tokens/${encodeURIComponent(token)}`, {
        method: 'DELETE',
      })
      if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`)
      await refreshUsers()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      markPending(token, false)
    }
  }

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(text)
      window.setTimeout(() => setCopied((c) => (c === text ? null : c)), 1500)
    } catch {
      /* clipboard unavailable — ignore */
    }
  }

  async function refreshSources() {
    try {
      const resp = await fetch('/advanced/sources')
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
      const resp = await fetch('/advanced/source-curation', {
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
    // Curation is keyed by gold_id on the backend (row.gold_id in the body);
    // the optimistic UI stays qa_id-keyed until the table is re-keyed to
    // gold_id in the frontend-gating slice (one gold per qa_id today).
    setRows((prev) =>
      prev?.map((r) => (r.qa_id === row.qa_id ? { ...r, included: next } : r)) ?? prev,
    )
    setPending((prev) => new Set(prev).add(row.qa_id))
    try {
      const resp = await fetch('/advanced/gold-curation', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ gold_id: row.gold_id, included: next }),
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

  async function refreshIndexBuilds() {
    try {
      const resp = await fetch('/advanced/index-builds')
      if (resp.ok) {
        const data = (await resp.json()) as { active_build_id: string | null; builds: IndexBuild[] }
        setIndexBuilds(data.builds)
        setActiveBuildId(data.active_build_id)
      }
    } catch {
      /* non-fatal — the list just won't populate */
    }
  }

  async function rebuildIndex() {
    if (rebuilding) return
    setRebuilding(true)
    setRebuildResult(null)
    try {
      const resp = await fetch('/advanced/rebuild-index', { method: 'POST' })
      if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`)
      const data: RebuildResult = await resp.json()
      setRebuildResult(data)
      // A rebuild may have picked up new files added on disk since page load.
      void refreshSources()
      void refreshIndexBuilds()
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

  // Fork someone else's gold into the caller's own editable copy (golds.clone).
  async function cloneGold(row: AdminGoldRow) {
    setError(null)
    try {
      const resp = await fetch(`/advanced/golds/${encodeURIComponent(row.gold_id)}/clone`, {
        method: 'POST',
      })
      if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`)
      await refresh()  // the clone now shows up as the caller's own gold
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
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

  // Client-side sorting for the two big tables. Slice() so we don't
  // mutate the state array in place.
  const sortedFeedback = feedback?.slice().sort((a, b) => {
    const { col, dir } = feedbackSort
    const mult = dir === 'asc' ? 1 : -1
    const av = col === 'has_gold' ? Number(a.has_gold) : a[col]
    const bv = col === 'has_gold' ? Number(b.has_gold) : b[col]
    if (av < bv) return -1 * mult
    if (av > bv) return 1 * mult
    return 0
  })

  const sortedSources = sources?.slice().sort((a, b) => {
    const { col, dir } = sourceSort
    const mult = dir === 'asc' ? 1 : -1
    const av = col === 'included' ? Number(a.included) : a[col]
    const bv = col === 'included' ? Number(b.included) : b[col]
    if (av < bv) return -1 * mult
    if (av > bv) return 1 * mult
    return 0
  })

  // Users tab: join the allowlist (who can log in) with role assignments,
  // keyed by token. Base rows on the allowlist — a role without an invite
  // entry can't sign in, so it isn't a "user" here.
  const roleByToken = new Map((roles ?? []).map((r) => [r.token, r]))
  // Rank a role by its position in the logical ladder (low→high) so Role
  // sorts by seniority, not alphabetically. Unknown roles sort last.
  const roleOrder = ladder.length > 0 ? ladder : ROLE_LADDER_FALLBACK
  const roleRank = (role: string): number => {
    const i = roleOrder.indexOf(role)
    return i === -1 ? roleOrder.length : i
  }
  const userRows: UserRow[] = (inviteTokens ?? [])
    .map((t) => {
      const r = roleByToken.get(t.token)
      return {
        token: t.token,
        label: t.label,
        role: r?.role ?? 'level1',
        source: r?.source ?? '—',
        lastSeen: t.last_seen,
        weeklyUsd: t.weekly_usd,
        weeklyTokens: t.weekly_tokens,
        questions: t.questions,
        comments: t.comments,
        golds: t.golds,
      }
    })
    .sort((a, b) => {
      const { col, dir } = userSort
      const mult = dir === 'asc' ? 1 : -1
      if (col === 'role') return (roleRank(a.role) - roleRank(b.role)) * mult
      if (col === 'weeklyTokens') return (a.weeklyTokens - b.weeklyTokens) * mult
      if (col === 'questions') return (a.questions - b.questions) * mult
      if (col === 'golds') return (a.golds - b.golds) * mult
      // ISO timestamps sort lexicographically = chronologically; never-seen
      // ('') sorts first, so ascending surfaces lurkers at the top.
      if (col === 'lastSeen') return (a.lastSeen ?? '').localeCompare(b.lastSeen ?? '') * mult
      // Label and Source are case-insensitive alphabetical.
      return String(a[col] ?? '').localeCompare(String(b[col] ?? ''), undefined, { sensitivity: 'base' }) * mult
    })
  // The Users tab shows with `users.view`; the controls inside gate on their
  // own caps (change_role / add / remove / rename), so level 7 (admin) manages
  // roles + invites while only level 8 removes/renames.
  const showUsersTab = can('users.view')
  const canManageUsers = can('users.view')

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border bg-card">
        <div className="px-6 py-4 md:pr-[19rem]">
          <div className="flex items-baseline justify-between gap-4">
            <div>
              <h1 className="text-xl font-semibold tracking-tight">
                Rulebook <span className="text-muted-foreground">/ Your activity</span>
              </h1>
              <p className="text-sm text-muted-foreground">
                {can('golds.curate')
                  ? 'Revisit your own work, curate golds and sources, and manage the index. Excluded rows are skipped by the next rebuild.'
                  : 'Revisit the questions, ratings, and golds you’ve contributed.'}
              </p>
            </div>
            <div className="flex flex-col items-end gap-1">
              {me?.recipient && (
                <span className="flex items-center gap-1.5 text-sm">
                  <span className="font-medium text-foreground">{me.recipient}</span>
                  {me.demo_mode && <LevelBadge level={me.level} />}
                </span>
              )}
              <a href="#/" className="text-sm text-muted-foreground hover:text-foreground hover:underline">
                ← back to Q&amp;A
              </a>
            </div>
          </div>
        </div>
      </header>

      {/* Left-aligned, full-width, with a right gutter reserving space for the
          floating widgets (they portal to <body> and show over this view too).
          Mirrors the main page's layout — content shifts left, widgets stay. */}
      <main className="space-y-4 px-6 py-6 md:pr-[19rem]">
        {error && (
          <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
            <div className="font-medium">Request failed</div>
            <div className="mt-1 whitespace-pre-wrap font-mono text-xs">{error}</div>
          </div>
        )}

        {!me && !meForbidden && !error && (
          <div className="text-sm text-muted-foreground">Checking access…</div>
        )}

        {meForbidden && (
          <div className="rounded-md border border-border bg-card p-6 text-sm text-muted-foreground shadow-sm">
            Your access has been suspended. Contact an admin if you think this is a mistake.
          </div>
        )}

        {me && !meForbidden && !canUseActivity && (
          <div className="rounded-md border border-border bg-card p-6 text-sm text-muted-foreground shadow-sm">
            You need to be signed in to see your activity.
          </div>
        )}

        {me && canUseActivity && (
          <>
        {/* Tab bar — each tab shows only if the caller's capabilities grant it.
            Counts baked into labels so both are visible regardless of active tab. */}
        <div className="flex gap-1 border-b border-border text-sm">
          {([
            ...(can('feedback.view') ? (['feedback'] as AdminTab[]) : []),
            ...(can('golds.view') ? (['golds'] as AdminTab[]) : []),
            ...(can('sources.view') ? (['sources'] as AdminTab[]) : []),
            ...(showUsersTab ? (['users'] as AdminTab[]) : []),
            ...(can('index.rebuild') ? (['indices'] as AdminTab[]) : []),
            ...(can('attribution.view') ? (['audit'] as AdminTab[]) : []),
          ] as AdminTab[]).map((t) => {
            const active = activeTab === t
            const label =
              t === 'feedback'
                ? `Feedback (${feedbackNeedsAttention} to review · ${feedbackTotal})`
                : t === 'golds'
                  ? `Golds (${goldIncluded}/${goldTotal})`
                  : t === 'sources'
                    ? `Sources (${sourceIncluded}/${sourceTotal})`
                    : t === 'audit'
                      ? `Audit${audit ? ` (${audit.length})` : ''}`
                      : t === 'indices'
                        ? 'Indices'
                        : canManageUsers
                          ? `Users (${userRows.length})`
                          : 'Users'
            return (
              <button
                key={t}
                type="button"
                onClick={() => setActiveTab(t)}
                className={
                  '-mb-px border-b-2 px-3 py-1.5 font-medium transition ' +
                  (active
                    ? 'border-primary text-foreground'
                    : 'border-transparent text-muted-foreground hover:text-foreground')
                }
              >
                {label}
              </button>
            )
          })}
        </div>

        {activeTab === 'feedback' && feedback === null && !error && (
          <div className="text-sm text-muted-foreground">Loading feedback…</div>
        )}
        {activeTab === 'feedback' && feedback !== null && feedback.length === 0 && (
          <div className="rounded-md border border-border bg-card p-6 text-sm text-muted-foreground shadow-sm">
            No feedback yet. Rate some answers in the main app.
          </div>
        )}
        {activeTab === 'feedback' && feedback !== null && feedback.length > 0 && (
          <section className="overflow-hidden rounded-md border border-border bg-card shadow-sm">
            <table className="w-full text-sm">
              <thead className="bg-muted text-left text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="w-16 px-3 py-2 text-center">
                    <button
                      type="button"
                      onClick={() => setFeedbackSort((s) => nextSort(s, 'rating'))}
                      className="hover:text-foreground"
                    >
                      rating{sortIndicator(feedbackSort.col === 'rating', feedbackSort.dir)}
                    </button>
                  </th>
                  <th className="w-16 px-3 py-2 text-center" title="Whether a gold answer has been saved for this qa_id">
                    <button
                      type="button"
                      onClick={() => setFeedbackSort((s) => nextSort(s, 'has_gold'))}
                      className="hover:text-foreground"
                    >
                      gold{sortIndicator(feedbackSort.col === 'has_gold', feedbackSort.dir)}
                    </button>
                  </th>
                  <th className="px-3 py-2">question / note</th>
                  <th className="w-40 px-3 py-2">tags</th>
                  <th className="w-40 px-3 py-2">
                    <button
                      type="button"
                      onClick={() => setFeedbackSort((s) => nextSort(s, 'timestamp'))}
                      className="hover:text-foreground"
                    >
                      when{sortIndicator(feedbackSort.col === 'timestamp', feedbackSort.dir)}
                    </button>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {sortedFeedback!.map((f) => {
                  const needsAttention = f.rating <= 3 && !f.has_gold
                  return (
                    <tr
                      key={f.qa_id + '-' + f.timestamp}
                      className={needsAttention ? 'bg-amber-50 hover:bg-amber-100' : 'hover:bg-accent'}
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
                          <span title="No gold yet" className="text-muted-foreground/50">·</span>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <div className="text-sm text-foreground">
                          {f.question || <span className="italic text-muted-foreground">(no qa_log entry)</span>}
                        </div>
                        {f.comment && (
                          <div className="mt-1 whitespace-pre-wrap text-xs text-muted-foreground">
                            {f.comment}
                          </div>
                        )}
                        <div className="mt-1 font-mono text-[10px] text-muted-foreground">
                          {f.qa_id.slice(0, 8)}
                        </div>
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex flex-wrap gap-1">
                          {f.tags.length === 0 ? (
                            <span className="text-xs text-muted-foreground">—</span>
                          ) : (
                            f.tags.map((t) => (
                              <span
                                key={t}
                                className="rounded bg-secondary px-1.5 py-0.5 font-mono text-[10px] text-foreground"
                              >
                                {t}
                              </span>
                            ))
                          )}
                        </div>
                      </td>
                      <td className="px-3 py-2 text-xs text-muted-foreground">
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
          <div className="text-sm text-muted-foreground">Loading golds…</div>
        )}
        {activeTab === 'golds' && rows !== null && rows.length === 0 && (
          <div className="rounded-md border border-border bg-card p-6 text-sm text-muted-foreground shadow-sm">
            No gold answers yet. Rate an answer in the main app and use the "Save gold answer" button.
          </div>
        )}
        {activeTab === 'golds' && rows !== null && rows.length > 0 && (
          <>
            <section className="overflow-hidden rounded-md border border-border bg-card shadow-sm">
              <table className="w-full text-sm">
                <thead className="bg-muted text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <tr>
                    <th className="w-16 px-3 py-2">incl.</th>
                    <th className="px-3 py-2">question</th>
                    <th className="w-40 px-3 py-2">saved</th>
                    <th className="w-24 px-3 py-2">qa_id</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {rows.map((r) => (
                    <Fragment key={r.qa_id}>
                      <tr className="hover:bg-accent">
                        <td className="px-3 py-2">
                          <button
                            type="button"
                            onClick={() => toggleInclusion(r)}
                            disabled={pending.has(r.qa_id) || !can('golds.curate')}
                            aria-pressed={r.included}
                            title={
                              !can('golds.curate')
                                ? (r.included ? 'Included' : 'Excluded')
                                : r.included
                                  ? 'Included — click to exclude'
                                  : 'Excluded — click to include'
                            }
                            className={
                              'inline-flex h-5 w-9 items-center rounded-full border transition ' +
                              (r.included
                                ? 'border-green-500 bg-green-500 justify-end'
                                : 'border-input bg-muted justify-start') +
                              (pending.has(r.qa_id) ? ' opacity-50' : '') +
                              (can('golds.curate') ? '' : ' cursor-not-allowed')
                            }
                          >
                            <span className="mx-0.5 h-4 w-4 rounded-full bg-card shadow-sm" />
                          </button>
                        </td>
                        <td className="px-3 py-2">
                          <button
                            type="button"
                            onClick={() => toggleExpanded(r.qa_id)}
                            className="text-left text-sm text-foreground hover:text-foreground"
                          >
                            {expanded.has(r.qa_id) ? '▼' : '▶'} {r.question}
                          </button>
                        </td>
                        <td className="px-3 py-2 text-xs text-muted-foreground">
                          {formatWhen(r.timestamp)}
                        </td>
                        <td className="px-3 py-2 font-mono text-xs text-muted-foreground">
                          {r.qa_id.slice(0, 8)}
                        </td>
                      </tr>
                      {expanded.has(r.qa_id) && (
                        <tr className="bg-muted">
                          <td />
                          <td colSpan={3} className="px-3 py-3">
                            {editingQaId === r.qa_id ? (
                              <div className="space-y-2">
                                <textarea
                                  value={editBuffer}
                                  onChange={(e) => setEditBuffer(e.target.value)}
                                  rows={12}
                                  className="w-full resize-y rounded-md border border-input bg-card p-2 font-mono text-xs shadow-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
                                />
                                <div className="flex items-center justify-between gap-3 text-xs">
                                  <span className="text-muted-foreground">
                                    Saves a new row to gold.jsonl. Rebuild index to make it retrievable.
                                    {editError && (
                                      <span className="ml-2 text-destructive">{editError}</span>
                                    )}
                                  </span>
                                  <span className="flex gap-2">
                                    <button
                                      type="button"
                                      onClick={cancelEdit}
                                      disabled={savingEdit}
                                      className="rounded-md border border-input bg-card px-2.5 py-1 text-xs font-medium text-foreground hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                                    >
                                      Cancel
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => saveEdit(r)}
                                      disabled={savingEdit || !editBuffer.trim() || editBuffer === r.gold_answer}
                                      className="rounded-md bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground shadow-sm hover:bg-primary/90 disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground"
                                    >
                                      {savingEdit ? 'Saving…' : 'Save'}
                                    </button>
                                  </span>
                                </div>
                              </div>
                            ) : (
                              <div className="space-y-2">
                                <pre className="whitespace-pre-wrap font-mono text-xs leading-relaxed text-foreground">
                                  {r.gold_answer}
                                </pre>
                                <div className="flex items-center justify-end gap-2">
                                  {!r.is_own && (
                                    <span className="text-xs text-muted-foreground">
                                      by {r.author ?? 'unknown'}
                                    </span>
                                  )}
                                  {r.is_own && can('golds.edit.own') && (
                                    <button
                                      type="button"
                                      onClick={() => beginEdit(r)}
                                      className="rounded-md border border-input bg-card px-2.5 py-1 text-xs font-medium text-foreground hover:bg-accent"
                                    >
                                      Edit
                                    </button>
                                  )}
                                  {!r.is_own && can('golds.clone') && (
                                    <button
                                      type="button"
                                      onClick={() => cloneGold(r)}
                                      title="Copy this into your own editable gold — the original is untouched"
                                      className="rounded-md border border-input bg-card px-2.5 py-1 text-xs font-medium text-foreground hover:bg-accent"
                                    >
                                      Clone
                                    </button>
                                  )}
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
          <div className="text-sm text-muted-foreground">Loading sources…</div>
        )}
        {activeTab === 'sources' && sources !== null && sources.length === 0 && (
          <div className="rounded-md border border-border bg-card p-6 text-sm text-muted-foreground shadow-sm">
            No source files found under <span className="font-mono">rules/&lt;sport&gt;/</span>.
          </div>
        )}
        {activeTab === 'sources' && sources !== null && sources.length > 0 && (
          <section className="overflow-hidden rounded-md border border-border bg-card shadow-sm">
            <table className="w-full text-sm">
              <thead className="bg-muted text-left text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="w-16 px-3 py-2">
                    <button
                      type="button"
                      onClick={() => setSourceSort((s) => nextSort(s, 'included'))}
                      className="hover:text-foreground"
                    >
                      incl.{sortIndicator(sourceSort.col === 'included', sourceSort.dir)}
                    </button>
                  </th>
                  <th className="w-28 px-3 py-2">
                    <button
                      type="button"
                      onClick={() => setSourceSort((s) => nextSort(s, 'sport'))}
                      className="hover:text-foreground"
                    >
                      sport{sortIndicator(sourceSort.col === 'sport', sourceSort.dir)}
                    </button>
                  </th>
                  <th className="px-3 py-2">
                    <button
                      type="button"
                      onClick={() => setSourceSort((s) => nextSort(s, 'path'))}
                      className="hover:text-foreground"
                    >
                      path{sortIndicator(sourceSort.col === 'path', sourceSort.dir)}
                    </button>
                  </th>
                  <th className="w-24 px-3 py-2 text-right">
                    <button
                      type="button"
                      onClick={() => setSourceSort((s) => nextSort(s, 'size_bytes'))}
                      className="hover:text-foreground"
                    >
                      size{sortIndicator(sourceSort.col === 'size_bytes', sourceSort.dir)}
                    </button>
                  </th>
                  <th className="w-40 px-3 py-2">
                    <button
                      type="button"
                      onClick={() => setSourceSort((s) => nextSort(s, 'modified_at'))}
                      className="hover:text-foreground"
                    >
                      modified{sortIndicator(sourceSort.col === 'modified_at', sourceSort.dir)}
                    </button>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {sortedSources!.map((s) => (
                  <tr key={s.path} className="hover:bg-accent">
                    <td className="px-3 py-2">
                      <button
                        type="button"
                        onClick={() => toggleSourceInclusion(s)}
                        disabled={sourcePending.has(s.path) || !can('sources.curate')}
                        aria-pressed={s.included}
                        title={
                          !can('sources.curate')
                            ? (s.included ? 'Included' : 'Excluded')
                            : s.included
                              ? 'Included — click to exclude'
                              : 'Excluded — click to include'
                        }
                        className={
                          'inline-flex h-5 w-9 items-center rounded-full border transition ' +
                          (s.included
                            ? 'border-green-500 bg-green-500 justify-end'
                            : 'border-input bg-muted justify-start') +
                          (sourcePending.has(s.path) ? ' opacity-50' : '') +
                          (can('sources.curate') ? '' : ' cursor-not-allowed')
                        }
                      >
                        <span className="mx-0.5 h-4 w-4 rounded-full bg-card shadow-sm" />
                      </button>
                    </td>
                    <td className="px-3 py-2">
                      <span className="rounded bg-secondary px-2 py-0.5 font-mono text-xs text-foreground">
                        {s.sport}
                      </span>
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-foreground">
                      {s.path}
                    </td>
                    <td className="px-3 py-2 text-right text-xs text-muted-foreground">
                      {formatBytes(s.size_bytes)}
                    </td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">
                      {formatWhen(s.modified_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}

        {activeTab === 'users' && !canManageUsers && (
          <div className="rounded-md border border-border bg-card p-6 text-sm text-muted-foreground shadow-sm">
            User management applies to a gated demo deploy. Set{' '}
            <span className="font-mono">RULEBOOK_DEMO_MODE=true</span> with{' '}
            <span className="font-mono">STATE_BACKEND_KIND=gcs</span>, and sign in as a{' '}
            <span className="font-mono">superuser</span>, to add invitees and change roles here.
          </div>
        )}

        {activeTab === 'users' && canManageUsers && (
          <div className="space-y-4">
            {/* Add invitee — allowlist entry (defaults to level 1 until promoted). */}
            {can('users.add') && (
            <section className="rounded-md border border-border bg-card p-4 shadow-sm">
              <div className="flex flex-wrap items-end gap-3">
                <label className="flex-1">
                  <span className="mb-1 block text-xs font-medium text-muted-foreground">Add invitee</span>
                  <input
                    type="text"
                    value={addLabel}
                    onChange={(e) => setAddLabel(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') void addUser()
                    }}
                    placeholder="Name or label, e.g. Alice"
                    className="w-full rounded-md border border-input bg-card px-2 py-1.5 text-sm shadow-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
                  />
                </label>
                <button
                  type="button"
                  onClick={() => void addUser()}
                  disabled={addPending || !addLabel.trim()}
                  className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground shadow-sm hover:bg-primary/90 disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground"
                >
                  {addPending ? 'Adding…' : 'Add'}
                </button>
              </div>
              {newInvite &&
                (() => {
                  const link = inviteLinkFor(newInvite.token, newInvite.label)
                  return (
                    <div className="mt-3 rounded-md border border-green-300 bg-green-50 p-3 text-xs text-green-900">
                      <div className="mb-1 font-medium">
                        Added {newInvite.label}. Share this invite link:
                      </div>
                      <div className="flex items-center gap-2">
                        <code className="flex-1 truncate rounded bg-card px-2 py-1 font-mono text-[11px] text-foreground">
                          {link}
                        </code>
                        <button
                          type="button"
                          onClick={() => void copy(link)}
                          className="rounded-md border border-green-300 bg-card px-2 py-1 font-medium text-green-800 hover:bg-green-100"
                        >
                          {copied === link ? 'Copied' : 'Copy link'}
                        </button>
                      </div>
                    </div>
                  )
                })()}
            </section>
            )}

            {inviteTokens === null && !error && (
              <div className="text-sm text-muted-foreground">Loading users…</div>
            )}
            {inviteTokens !== null && userRows.length === 0 && (
              <div className="rounded-md border border-border bg-card p-6 text-sm text-muted-foreground shadow-sm">
                No invitees yet. Add one above.
              </div>
            )}
            {inviteTokens !== null && userRows.length > 0 && (
              <section className="w-full overflow-x-auto rounded-md border border-border bg-card shadow-sm">
                <table className="w-full text-sm">
                  <thead className="bg-muted text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2">
                        <button
                          type="button"
                          onClick={() => setUserSort((s) => nextSort(s, 'label'))}
                          className="uppercase hover:text-foreground"
                        >
                          name{sortIndicator(userSort.col === 'label', userSort.dir)}
                        </button>
                      </th>
                      <th className="px-3 py-2">invite</th>
                      <th className="px-3 py-2">
                        <button
                          type="button"
                          onClick={() => setUserSort((s) => nextSort(s, 'role'))}
                          className="uppercase hover:text-foreground"
                        >
                          role{sortIndicator(userSort.col === 'role', userSort.dir)}
                        </button>
                      </th>
                      <th className="px-3 py-2">
                        <button
                          type="button"
                          onClick={() => setUserSort((s) => nextSort(s, 'lastSeen'))}
                          className="uppercase hover:text-foreground"
                          title="Most recent visit (any page load) or question"
                        >
                          last seen{sortIndicator(userSort.col === 'lastSeen', userSort.dir)}
                        </button>
                      </th>
                      <th className="px-3 py-2 text-right">
                        <button
                          type="button"
                          onClick={() => setUserSort((s) => nextSort(s, 'questions'))}
                          className="uppercase hover:text-foreground"
                          title="Lifetime questions asked"
                        >
                          # questions{sortIndicator(userSort.col === 'questions', userSort.dir)}
                        </button>
                      </th>
                      <th className="px-3 py-2 text-right">
                        <button
                          type="button"
                          onClick={() => setUserSort((s) => nextSort(s, 'golds'))}
                          className="uppercase hover:text-foreground"
                          title="Gold answers this user owns"
                        >
                          # gold{sortIndicator(userSort.col === 'golds', userSort.dir)}
                        </button>
                      </th>
                      <th className="px-3 py-2 text-right">
                        <button
                          type="button"
                          onClick={() => setUserSort((s) => nextSort(s, 'weeklyTokens'))}
                          className="uppercase hover:text-foreground"
                          title="This week's spend · tokens (resets Monday)"
                        >
                          this week{sortIndicator(userSort.col === 'weeklyTokens', userSort.dir)}
                        </button>
                      </th>
                      <th className="px-3 py-2 text-right">actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {userRows.map((u) => {
                      const busy = userPending.has(u.token)
                      const isSelf = me?.recipient != null && me.recipient === u.label
                      return (
                        <tr
                          key={u.token}
                          className={'hover:bg-accent' + (busy ? ' opacity-50' : '')}
                        >
                          <td className="whitespace-nowrap px-3 py-2 text-foreground">
                            {editingToken === u.token ? (
                              <div className="flex items-center gap-1.5">
                                <input
                                  type="text"
                                  autoFocus
                                  value={editName}
                                  disabled={busy}
                                  onChange={(e) => setEditName(e.target.value)}
                                  onKeyDown={(e) => {
                                    if (e.key === 'Enter') void renameUser(u.token, u.label)
                                    if (e.key === 'Escape') cancelRename()
                                  }}
                                  className="w-full min-w-[12rem] rounded-md border border-input bg-card px-2 py-1 text-sm shadow-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
                                />
                                <button
                                  type="button"
                                  onClick={() => void renameUser(u.token, u.label)}
                                  disabled={busy || !editName.trim()}
                                  title="Save name"
                                  className="rounded-md bg-primary px-2 py-1 text-xs font-medium text-primary-foreground shadow-sm hover:bg-primary/90 disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground"
                                >
                                  Save
                                </button>
                                <button
                                  type="button"
                                  onClick={cancelRename}
                                  disabled={busy}
                                  title="Cancel"
                                  className="rounded-md border border-input bg-card px-2 py-1 text-xs font-medium text-foreground hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                                >
                                  Cancel
                                </button>
                              </div>
                            ) : can('users.rename') ? (
                              <button
                                type="button"
                                onClick={() => beginRename(u.token, u.label)}
                                title="Click to rename"
                                className="rounded px-1 -mx-1 text-left hover:bg-accent hover:underline decoration-dotted underline-offset-4"
                              >
                                {u.label}
                              </button>
                            ) : (
                              <span>{u.label}</span>
                            )}
                          </td>
                          <td className="px-3 py-2">
                            <button
                              type="button"
                              onClick={() => void copy(inviteLinkFor(u.token, u.label))}
                              title="Click to copy this user's invite link"
                              className="font-mono text-xs text-muted-foreground hover:text-foreground"
                            >
                              {u.token.slice(0, 12)}…{copied === inviteLinkFor(u.token, u.label) ? ' ✓' : ''}
                            </button>
                          </td>
                          <td className="px-3 py-2">
                            <select
                              value={u.role}
                              disabled={busy || !can('users.change_role')}
                              onChange={(e) => void changeRole(u.token, e.target.value)}
                              title={levelInfo(levelNumber(u.role)).description}
                              className="rounded-md border border-input bg-card px-2 py-1 text-xs shadow-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
                            >
                              {ladder.map((r) => (
                                <option key={r} value={r}>
                                  {levelInfo(levelNumber(r)).name}
                                </option>
                              ))}
                            </select>
                          </td>
                          <td
                            className="whitespace-nowrap px-3 py-2 text-xs text-muted-foreground"
                            title={u.lastSeen ?? 'not seen since tracking began'}
                          >
                            {fmtRelative(u.lastSeen)}
                          </td>
                          <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-xs tabular-nums text-muted-foreground">
                            {u.questions > 0 ? u.questions : '—'}
                          </td>
                          <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-xs tabular-nums text-muted-foreground">
                            {u.golds > 0 ? u.golds : '—'}
                          </td>
                          <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-xs tabular-nums text-muted-foreground">
                            {fmtEngagement(u.weeklyUsd, u.weeklyTokens)}
                          </td>
                          <td className="px-3 py-2">
                            <div className="flex justify-end gap-2 text-xs">
                              {can('users.change_role') && (
                                <button
                                  type="button"
                                  onClick={() => void resetRole(u.token)}
                                  disabled={busy || u.source !== 'override'}
                                  title={
                                    u.source === 'override'
                                      ? 'Clear this live role change → fall back to the seed (or Beginner)'
                                      : 'Nothing to reset — this role isn’t a live override'
                                  }
                                  className="rounded-md border border-input bg-card px-2 py-1 font-medium text-foreground hover:bg-accent disabled:cursor-not-allowed disabled:opacity-40"
                                >
                                  Reset
                                </button>
                              )}
                              {can('users.remove') && (
                                <button
                                  type="button"
                                  onClick={() => void removeUser(u.token, u.label)}
                                  disabled={busy || isSelf}
                                  title={isSelf ? "You can't remove yourself" : 'Hard-delete this invite'}
                                  className="rounded-md border border-destructive/30 bg-card px-2 py-1 font-medium text-destructive hover:bg-destructive/10 disabled:cursor-not-allowed disabled:opacity-40"
                                >
                                  Remove
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </section>
            )}
          </div>
        )}

        {activeTab === 'audit' && audit === null && !error && (
          <div className="text-sm text-muted-foreground">Loading audit trail…</div>
        )}
        {activeTab === 'audit' && audit !== null && audit.length === 0 && (
          <div className="rounded-md border border-border bg-card p-6 text-sm text-muted-foreground shadow-sm">
            No shared-state changes recorded yet. Curating a gold, rebuilding the index, or
            changing a user all land here.
          </div>
        )}
        {activeTab === 'audit' && audit !== null && audit.length > 0 && (
          <section className="overflow-hidden rounded-md border border-border bg-card shadow-sm">
            <table className="w-full text-sm">
              <thead className="bg-muted text-left text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="w-44 px-3 py-2">when</th>
                  <th className="w-32 px-3 py-2">who</th>
                  <th className="w-40 px-3 py-2">action</th>
                  <th className="px-3 py-2">target</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {audit.map((a, i) => (
                  <tr key={a.timestamp + '-' + i} className="hover:bg-accent">
                    <td className="px-3 py-2 font-mono text-xs text-muted-foreground">
                      {a.timestamp.replace('T', ' ').slice(0, 19)}
                    </td>
                    <td className="px-3 py-2">{a.actor ?? '—'}</td>
                    <td className="px-3 py-2 font-mono text-xs">{a.action}</td>
                    <td className="px-3 py-2 font-mono text-xs text-muted-foreground">
                      {a.target ?? ''}
                      {a.detail && Object.keys(a.detail).length > 0 && (
                        <span className="ml-2 text-muted-foreground/70">
                          {JSON.stringify(a.detail)}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}

        {activeTab === 'indices' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between gap-3">
              <span className="text-xs text-muted-foreground">
                {indexBuilds === null
                  ? 'Loading…'
                  : `${indexBuilds.length} build${indexBuilds.length === 1 ? '' : 's'} recorded · newest first`}
              </span>
              <button
                type="button"
                onClick={rebuildIndex}
                disabled={rebuilding}
                title="Runs scripts/build_index.py — typically 15s, occasionally a minute or two when Voyage is slow"
                className="rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground shadow-sm hover:bg-primary/90 disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground"
              >
                {rebuilding ? 'Rebuilding…' : 'Rebuild index'}
              </button>
            </div>

            {indexBuilds !== null && indexBuilds.length === 0 && (
              <div className="rounded-md border border-border bg-card p-6 text-sm text-muted-foreground shadow-sm">
                No index builds recorded yet — click Rebuild index.
              </div>
            )}
            {indexBuilds !== null && indexBuilds.length > 0 && (
              <section className="overflow-x-auto rounded-md border border-border bg-card shadow-sm">
                <table className="w-full text-sm">
                  <thead className="bg-muted text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <tr>
                      <th className="w-6 px-2 py-2"></th>
                      <th className="px-3 py-2">built</th>
                      <th className="px-3 py-2">build</th>
                      <th className="px-3 py-2 text-right">chunks</th>
                      <th className="px-3 py-2 text-right">sources</th>
                      <th className="px-3 py-2 text-right">golds</th>
                      <th className="px-3 py-2"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {indexBuilds.map((b, i) => {
                      const active = b.build_id != null && b.build_id === activeBuildId
                      const expanded = b.build_id != null && b.build_id === expandedBuild
                      return (
                        <Fragment key={b.build_id ?? i}>
                          <tr
                            onClick={() => setExpandedBuild(expanded ? null : b.build_id)}
                            title="Click to see the sources and golds in this build"
                            className={'cursor-pointer ' + (active ? 'bg-accent/40' : 'hover:bg-accent/30')}
                          >
                            <td className="px-2 py-2 text-[10px] text-muted-foreground">{expanded ? '▼' : '▶'}</td>
                            <td className="whitespace-nowrap px-3 py-2 text-foreground">
                              {b.built_at ? new Date(b.built_at).toLocaleString() : '—'}
                            </td>
                            <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-muted-foreground">
                              {b.build_num} ({b.git_sha})
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums">{b.count}</td>
                            <td className="px-3 py-2 text-right tabular-nums">{b.sources.length}</td>
                            <td className="px-3 py-2 text-right tabular-nums">{b.gold_answers}</td>
                            <td className="px-3 py-2">
                              {active && (
                                <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[11px] font-medium text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300">
                                  active
                                </span>
                              )}
                            </td>
                          </tr>
                          {expanded && (
                            <tr className="bg-muted/30">
                              <td></td>
                              <td colSpan={6} className="px-3 py-3">
                                <div className="grid gap-5 md:grid-cols-2">
                                  <div>
                                    <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                                      sources ({b.sources.length})
                                    </div>
                                    <ul className="space-y-1">
                                      {b.sources.map((s, j) => (
                                        <li key={j} className="font-mono text-[11px]">
                                          <span className="mr-1.5 rounded bg-muted px-1 py-0.5 text-muted-foreground">{s.sport}</span>
                                          <span className="text-foreground">{s.file}</span>
                                        </li>
                                      ))}
                                    </ul>
                                  </div>
                                  <div>
                                    <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                                      golds ({b.gold_answers} → {b.gold_chunks} chunks)
                                    </div>
                                    {b.golds.length === 0 ? (
                                      <div className="text-xs text-muted-foreground">none</div>
                                    ) : (
                                      <ul className="space-y-1">
                                        {b.golds.map((g, j) => (
                                          <li key={j} className="truncate text-xs">
                                            <span className="text-muted-foreground">{g.author ?? '—'}: </span>
                                            <span className="text-foreground">{g.question || '(no question text)'}</span>
                                          </li>
                                        ))}
                                      </ul>
                                    )}
                                  </div>
                                </div>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      )
                    })}
                  </tbody>
                </table>
              </section>
            )}

            {rebuildResult && (
              <div
                className={
                  'rounded-md border p-3 text-xs ' +
                  (rebuildResult.ok
                    ? 'border-green-300 bg-green-50 text-green-900'
                    : 'border-destructive/30 bg-destructive/10 text-destructive')
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
          </div>
        )}
          </>
        )}
      </main>
    </div>
  )
}
