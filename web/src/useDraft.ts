// Copyright (c) 2026 Eric Cooper.
import { useCallback, useEffect, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'

const PREFIX = 'rulebook.draft.'

// The localStorage key for one user's copy of something saved in the browser.
// Several people can sign in on one browser; each gets their own copy, so one
// person's question or answer never appears for the next.
export function ownedKey(base: string, owner: string): string {
  return `${base}:${owner}`
}

// #176: persist a text draft to localStorage so a reload — a version update via
// the #175 banner, an accidental refresh, or a browser restart — doesn't lose
// in-progress writing. Same best-effort localStorage approach as the tab
// persistence (#163). Drop-in for useState<string>, plus a clear().
//
// The draft belongs to `owner` (the signed-in recipient; '' when there are no
// identities). Until the owner is known (`undefined`, while /me loads) nothing is
// read or written; once known, that owner's saved draft is loaded.
//
// Best-effort: localStorage can throw (private mode / quota); a failure just
// means the draft isn't persisted, never that the app breaks.
export function usePersistentDraft(
  key: string,
  owner: string | undefined,
  initial = '',
): [string, Dispatch<SetStateAction<string>>, () => void] {
  const base = PREFIX + key
  const [value, setValue] = useState<string>(initial)
  // Whose draft `value` is. Loading during render (not in an effect) means the
  // save effect below never runs with the owner known but the draft unloaded.
  const [loadedFor, setLoadedFor] = useState<string | undefined>(undefined)
  if (owner !== undefined && owner !== loadedFor) {
    setLoadedFor(owner)
    try {
      localStorage.removeItem(base) // the shared key used before drafts had owners
      const saved = localStorage.getItem(ownedKey(base, owner))
      if (saved !== null && value === '') setValue(saved)
    } catch {
      // ignore — persistence is best-effort
    }
  }
  useEffect(() => {
    if (loadedFor === undefined) return
    try {
      if (value) localStorage.setItem(ownedKey(base, loadedFor), value)
      else localStorage.removeItem(ownedKey(base, loadedFor))
    } catch {
      // ignore — persistence is best-effort
    }
  }, [base, loadedFor, value])
  const clear = useCallback(() => setValue(''), [])
  return [value, setValue, clear]
}
