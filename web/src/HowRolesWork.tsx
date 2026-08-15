// Copyright (c) 2026 Eric Cooper.
//
// "How roles work" — a friendly, honest tour of the role ladder (issue #40).
// Companion to HowItWorks. Renders the rungs from LEVELS (the single source of
// truth, mirrored from roles.py), highlights where the viewer currently stands,
// and is upfront that advancement is granted by curators, not earned by points.

import { useEffect } from 'react'
import { LEVELS } from './levels'

export function HowRolesWork({
  currentLevel,
  onClose,
}: {
  currentLevel: number
  onClose: () => void
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // Rungs 1–8 form the ladder; level 0 (Suspended) is an aside, not a step.
  const rungs = LEVELS.map((info, level) => ({ ...info, level })).filter((r) => r.level >= 1)

  return (
    <div
      className="fixed inset-0 z-50 flex justify-center overflow-y-auto bg-black/40 p-4 sm:p-8"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="How roles work"
    >
      <div
        className="my-auto w-full max-w-2xl rounded-xl border border-border bg-card p-6 shadow-lg sm:p-8"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-5 flex items-start justify-between gap-4">
          <h2 className="text-lg font-medium text-foreground">How roles work</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="-mr-1 -mt-1 rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            ✕
          </button>
        </div>

        <p className="mb-5 text-sm leading-relaxed text-muted-foreground">
          Rulebook grows with you. Everyone starts able to ask questions and rate answers; as you
          contribute, curators widen what you can do. There's nothing to grind for — roles are{' '}
          <strong className="font-medium text-foreground">granted, not earned by points</strong>.
          Here's the whole ladder, and where you stand on it.
        </p>

        <ol className="space-y-1.5">
          {rungs.map((r) => {
            const isCurrent = r.level === currentLevel
            return (
              <li
                key={r.level}
                className={
                  'flex items-start gap-3 rounded-md px-2.5 py-2 ' +
                  (isCurrent ? 'bg-accent ring-1 ring-inset ring-border' : '')
                }
              >
                <span
                  aria-hidden
                  className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full ring-1 ring-inset ring-foreground/30"
                  style={{ background: r.color }}
                />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <span className="text-sm font-medium text-foreground">{r.name}</span>
                    {isCurrent && (
                      <span className="rounded bg-foreground px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-background">
                        You're here
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-muted-foreground">{r.unlocks}</p>
                </div>
              </li>
            )
          })}
        </ol>

        <p className="mt-5 border-t border-border pt-4 text-xs text-muted-foreground">
          Each rung keeps everything below it. A suspended account has no access. Want to do more?
          Just keep contributing — a curator can widen your role.
        </p>
      </div>
    </div>
  )
}
