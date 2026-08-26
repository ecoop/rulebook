import { useCallback, useEffect, useRef, useState } from 'react'

// #175: notice when a newer server build has been deployed and offer an in-app
// reload. Detection is client-only — /meta already reports build_num, so we
// remember the build we loaded on and watch for it to change (on focus + a
// light poll). We PROMPT, never auto-reload: a reload discards in-progress work
// (an unsent question, an unsaved gold/comment), so the user reloads when it's
// convenient. (#176 persists drafts so the reload becomes lossless.)
//
// Self-contained (its own tiny /meta fetch) so it can sit above both views in
// main.tsx and show regardless of which one is open.
export default function NewVersionBanner() {
  const loadedBuild = useRef<string | null>(null)
  const [newBuild, setNewBuild] = useState<string | null>(null)
  const [dismissed, setDismissed] = useState(false)

  const check = useCallback(() => {
    fetch('/meta')
      .then((r) => (r.ok ? r.json() : Promise.reject(r.statusText)))
      .then((m: { build_num?: string }) => {
        const b = m.build_num
        // Ignore unknown builds ('?' / missing) — common in local dev — so we
        // never flash a spurious banner.
        if (!b || b === '?') return
        if (loadedBuild.current === null) {
          loadedBuild.current = b
        } else if (b !== loadedBuild.current) {
          setNewBuild(b)
        }
      })
      .catch(() => {
        // Non-fatal: a failed /meta just means we skip this check.
      })
  }, [])

  useEffect(() => {
    check()
    const onFocus = () => check()
    window.addEventListener('focus', onFocus)
    const id = window.setInterval(() => {
      if (!document.hidden) check()
    }, 60_000)
    return () => {
      window.removeEventListener('focus', onFocus)
      window.clearInterval(id)
    }
  }, [check])

  if (!newBuild || dismissed) return null

  return (
    <div className="flex items-center justify-between gap-3 border-b border-border bg-accent px-4 py-2 text-sm text-accent-foreground">
      <span>
        A new version of Rulebook is available. Reload to update — anything you've
        submitted is saved.
      </span>
      <div className="flex shrink-0 items-center gap-2">
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground shadow-sm hover:bg-primary/90"
        >
          Reload
        </button>
        <button
          type="button"
          onClick={() => setDismissed(true)}
          aria-label="Dismiss"
          className="rounded p-1 text-lg leading-none text-muted-foreground hover:text-foreground"
        >
          ×
        </button>
      </div>
    </div>
  )
}
