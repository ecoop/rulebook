// Copyright (c) 2026 Eric Cooper.
//
// App-level show/hide for the whole floating-widget HUD, shared by both pages
// (the main Q&A page owns the stack; the activity page's header needs the same
// toggle). This is deliberately ABOVE the floating-widgets library: the library
// handles float-vs-dock responsively, but has no notion of "hidden entirely" on
// desktop — that's a user preference the app owns.
//
// `hasNew` is a small "there's something new behind the hidden HUD" flag — set
// when the user asks a question while the widgets are hidden (their usage just
// moved), cleared when they show the HUD again. It tints the eye so a hidden
// HUD can still signal fresh info.

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'

interface WidgetVisibility {
  hidden: boolean
  hasNew: boolean
  toggle: () => void
  markNew: () => void
}

const Ctx = createContext<WidgetVisibility | null>(null)

export function WidgetVisibilityProvider({ children }: { children: ReactNode }) {
  const [hidden, setHidden] = useState(false)
  const [hasNew, setHasNew] = useState(false)
  // Stable identities so consumer effects that depend on markNew don't re-run
  // on every provider render.
  const toggle = useCallback(
    () =>
      setHidden((h) => {
        if (h) setHasNew(false) // showing the HUD clears the "new" flag
        return !h
      }),
    [],
  )
  const markNew = useCallback(() => setHasNew(true), [])
  const value = useMemo(
    () => ({ hidden, hasNew, toggle, markNew }),
    [hidden, hasNew, toggle, markNew],
  )
  return <Ctx value={value}>{children}</Ctx>
}

export function useWidgetVisibility(): WidgetVisibility {
  const v = useContext(Ctx)
  if (!v) throw new Error('useWidgetVisibility must be used within WidgetVisibilityProvider')
  return v
}
