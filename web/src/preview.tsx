// "View as level" preview — a superuser sees the whole app as any level 0–8
// without reassigning users and reloading. Two identities coexist here
// (docs/rbac-capabilities.md): the REAL identity (from /me) owns page access,
// the View-as control, and every data fetch; the PREVIEW level drives ALL
// tab/column/button gating. So `caps = previewLevel != null ? roleCaps[levelN]
// : me.capabilities`.
//
// The state lives ABOVE both views (in main.tsx's Root) and is shared through
// this context, so "View as Beginner" reshapes the Main page AND the Advanced
// page at once. Critically, the exit affordance is a PERSISTENT top-level
// banner rendered from the real identity — the previewed chrome (e.g. a level-1
// Q&A page) has no Advanced button and no controls, so the only way back must
// live outside it. Standard impersonation pattern (Stripe / Django admin).

import { createContext, useContext } from 'react'
import { LevelBadge, levelInfo, levelLabel } from './levels'

export interface PreviewState {
  // The level being previewed (0–8), or null when viewing as your real self.
  previewLevel: number | null
  setPreviewLevel: (level: number | null) => void
  // level id ("level0"…"level8") → sorted capability bundle, from
  // GET /advanced/role-capabilities. null until loaded.
  roleCaps: Record<string, string[]> | null
}

const PreviewContext = createContext<PreviewState>({
  previewLevel: null,
  setPreviewLevel: () => {},
  roleCaps: null,
})

export const PreviewProvider = PreviewContext.Provider

export function usePreview(): PreviewState {
  return useContext(PreviewContext)
}

// The capabilities the UI should gate on: the previewed level's bundle while
// previewing, otherwise the caller's real bundle. Falls back to the real caps
// if the map hasn't loaded — gating never opens up more than the real user
// actually holds (preview is only offered to a superuser, who has everything).
export function useEffectiveCaps(realCaps: string[]): string[] {
  const { previewLevel, roleCaps } = usePreview()
  if (previewLevel == null) return realCaps
  return roleCaps?.['level' + previewLevel] ?? realCaps
}

// The level to display (badge, "your level" copy): the previewed level while
// previewing, otherwise the real level. (`?? ` preserves level 0, unlike `||`.)
export function useEffectiveLevel(realLevel: number): number {
  const { previewLevel } = usePreview()
  return previewLevel ?? realLevel
}

// A persistent, top-level bar owned by the REAL identity. When previewing it's
// a full-width sticky banner with the level + an Exit; otherwise a compact
// launcher offered only to a superuser. Rendered in main.tsx above both views.
export function PreviewBar({
  canPreview,
  maxLevel,
  previewLevel,
  setPreviewLevel,
}: {
  // Whether to offer the launcher (real user may preview and the map is loaded).
  canPreview: boolean
  // Cap the selectable levels at the viewer's own level — previewing higher is
  // meaningless (you'd have no data and no more access than you do now).
  maxLevel: number
  previewLevel: number | null
  setPreviewLevel: (level: number | null) => void
}) {
  const levels = Array.from({ length: maxLevel + 1 }, (_, i) => i)

  if (previewLevel != null) {
    const info = levelInfo(previewLevel)
    return (
      <div
        style={{ position: 'fixed', left: 0, right: 0, bottom: 0, zIndex: 9999 }}
        className="border-t border-amber-400 bg-amber-50 text-amber-950 shadow-[0_-2px_12px_rgba(0,0,0,0.12)] dark:border-amber-500/50 dark:bg-amber-950/95 dark:text-amber-100"
      >
        <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-3 gap-y-1.5 px-4 py-2 text-sm">
          <span aria-hidden className="text-base leading-none">👁</span>
          <span className="font-medium">Viewing as</span>
          <LevelBadge level={previewLevel} />
          <span className="font-medium">Level {previewLevel}</span>
          <span className="text-amber-900/80 dark:text-amber-200/80">· {info.description}</span>
          <span
            className="hidden cursor-help text-xs text-amber-900/70 underline decoration-dotted underline-offset-2 dark:text-amber-200/70 sm:inline"
            title={
              'Preview changes only what is VISIBLE — which tabs, buttons, and panels show. ' +
              'It does NOT re-scope server data: rows and counts stay yours, and any action you ' +
              'take still runs as your real superuser identity. True impersonation (backend ' +
              'act-as with real data scoping) is a separate, security-sensitive follow-up.'
            }
          >
            visibility only, not data ⓘ
          </span>
          <div className="ml-auto flex items-center gap-2">
            <label className="flex items-center gap-1.5 text-xs text-amber-900/80 dark:text-amber-200/80">
              <span className="hidden sm:inline">switch to</span>
              <select
                value={previewLevel}
                onChange={(e) => setPreviewLevel(Number(e.target.value))}
                className="rounded-md border border-amber-400 bg-white px-2 py-1 text-xs text-amber-950 shadow-sm focus:outline-none focus:ring-1 focus:ring-amber-500 dark:border-amber-500/60 dark:bg-amber-900 dark:text-amber-50"
              >
                {levels.map((n) => (
                  <option key={n} value={n}>
                    {levelLabel(n)}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              onClick={() => setPreviewLevel(null)}
              className="rounded-md bg-amber-600 px-3 py-1 text-xs font-medium text-white shadow-sm hover:bg-amber-700"
            >
              Exit preview
            </button>
          </div>
        </div>
      </div>
    )
  }

  if (!canPreview) return null

  // Inactive: a compact launcher, bottom-left so it clears the floating widget
  // stack (top-right). Selecting a level enters preview.
  return (
    <div style={{ position: 'fixed', left: 12, bottom: 12, zIndex: 9998 }}>
      <label
        title="See the app as a lower level would — visibility preview only"
        className="flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1.5 text-xs shadow-md"
      >
        <span aria-hidden>👁</span>
        <span className="text-muted-foreground">View as</span>
        <select
          value=""
          onChange={(e) => {
            if (e.target.value !== '') setPreviewLevel(Number(e.target.value))
          }}
          className="bg-transparent text-foreground focus:outline-none"
        >
          <option value="">your role…</option>
          {levels.map((n) => (
            <option key={n} value={n}>
              {levelLabel(n)}
            </option>
          ))}
        </select>
      </label>
    </div>
  )
}
