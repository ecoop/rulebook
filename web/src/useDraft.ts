import { useCallback, useEffect, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'

const PREFIX = 'rulebook.draft.'

// #176: persist a text draft to localStorage so a reload — a version update via
// the #175 banner, an accidental refresh, or a browser restart — doesn't lose
// in-progress writing. Same best-effort localStorage approach as the tab
// persistence (#163). Drop-in for useState<string>, plus a clear().
//
// Best-effort: localStorage can throw (private mode / quota); a failure just
// means the draft isn't persisted, never that the app breaks.
export function usePersistentDraft(
  key: string,
  initial = '',
): [string, Dispatch<SetStateAction<string>>, () => void] {
  const storageKey = PREFIX + key
  const [value, setValue] = useState<string>(() => {
    try {
      return localStorage.getItem(storageKey) ?? initial
    } catch {
      return initial
    }
  })
  useEffect(() => {
    try {
      if (value) localStorage.setItem(storageKey, value)
      else localStorage.removeItem(storageKey)
    } catch {
      // ignore — persistence is best-effort
    }
  }, [storageKey, value])
  const clear = useCallback(() => {
    setValue('')
    try {
      localStorage.removeItem(storageKey)
    } catch {
      // ignore
    }
  }, [storageKey])
  return [value, setValue, clear]
}
