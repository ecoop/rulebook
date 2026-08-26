import { useCallback, useEffect, useRef, useState } from 'react'

import { CLIENT_BUILD, CLIENT_BUILD_KNOWN } from './buildInfo'

// #175: notice when a newer server build has been deployed and offer an in-app
// reload. We PROMPT, never auto-reload: a reload discards in-progress work (an
// unsent question, an unsaved gold/comment), so the user reloads when it's
// convenient. (#176 persists drafts so the reload is lossless.)
//
// Detection compares the server's build (/meta.build_num) against the build
// THIS bundle was compiled at (CLIENT_BUILD, baked in at build time). That's
// exact — unlike the old "first /meta seen" heuristic, which couldn't tell a
// reloaded-and-current tab from a stale one. When the client build wasn't
// injected ("?" — local dev, or a --no-cache deploy) we fall back to that
// heuristic so dev still behaves.
//
// Self-contained (its own tiny /meta fetch) so it can sit above both views in
// main.tsx and show regardless of which one is open.
export default function NewVersionBanner() {
  const firstSeen = useRef<string | null>(null) // fallback baseline when CLIENT_BUILD is unknown
  const [serverBuild, setServerBuild] = useState<string | null>(null)

  const check = useCallback(() => {
    fetch('/meta')
      .then((r) => (r.ok ? r.json() : Promise.reject(r.statusText)))
      .then((m: { build_num?: string }) => {
        const server = m.build_num
        // Ignore unknown server builds ('?' / missing) — common in local dev.
        if (!server || server === '?') return
        if (CLIENT_BUILD_KNOWN) {
          if (server !== CLIENT_BUILD) setServerBuild(server)
        } else {
          // Fallback: no baked build to compare against — watch for the server
          // build to change from whatever we first saw.
          if (firstSeen.current === null) firstSeen.current = server
          else if (server !== firstSeen.current) setServerBuild(server)
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

  const [dismissed, setDismissed] = useState<string | null>(null)
  // Re-show if a still-newer build lands after a dismiss.
  if (!serverBuild || dismissed === serverBuild) return null

  return (
    <div className="flex items-center justify-between gap-3 border-b border-border bg-accent px-4 py-2 text-sm text-accent-foreground">
      <span>
        A new version of Rulebook is available
        {CLIENT_BUILD_KNOWN ? ` (build ${serverBuild}; you're on ${CLIENT_BUILD})` : ''}.
        Reload to update — anything you've submitted is saved.
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
          onClick={() => setDismissed(serverBuild)}
          aria-label="Dismiss"
          className="rounded p-1 text-lg leading-none text-muted-foreground hover:text-foreground"
        >
          ×
        </button>
      </div>
    </div>
  )
}
