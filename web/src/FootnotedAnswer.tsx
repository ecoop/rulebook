// Copyright (c) 2026 Eric Cooper.
// The answer with its [domain rule_id] citations as numbered footnotes, and the
// cited sources listed once underneath. Shared by the Q&A page and Your activity.
//
// With the passages the answer was given (`chunks`, the Q&A page), each source
// shows its rule, pages and the passage's opening words, and opens that passage.
// Without them (Your activity keeps only the answer text), each source shows its
// rule set and rule id, and a citation counts when it names one of `domains`.
import { lazy, Suspense, useMemo, useState } from 'react'
import { type CitableChunk, citedMarkdown, excerpt, footnoteCitations, pagesLabel } from './citations'

// The Markdown parser is most of the renderer's weight; load it with the first answer.
const AnswerMarkdown = lazy(() => import('./AnswerMarkdown'))
const NONE: string[] = []

export function FootnotedAnswer({
  answer,
  chunks,
  unverified = NONE,
  domains = NONE,
  onOpenPassage,
  idPrefix = '',
}: {
  answer: string
  chunks?: CitableChunk[]
  unverified?: string[]
  domains?: string[]
  onOpenPassage?: (i: number) => void
  // Prefix for the footnote anchors, so several answers on one page don't share ids.
  idPrefix?: string
}) {
  const { segments, sources } = useMemo(
    () => footnoteCitations(answer, chunks ?? [], unverified, domains),
    [answer, chunks, unverified, domains],
  )
  const [hovered, setHovered] = useState<number | null>(null)
  const markdown = useMemo(() => citedMarkdown(segments), [segments])
  return (
    <>
      <div className="text-sm leading-relaxed text-foreground">
        <Suspense fallback={<div className="whitespace-pre-wrap">{answer}</div>}>
          <AnswerMarkdown markdown={markdown} onHover={setHovered} idPrefix={idPrefix} />
        </Suspense>
      </div>
      {sources.length > 0 && (
        <ol className="mt-3 space-y-0.5 border-t border-border pt-2 text-xs text-muted-foreground">
          {sources.map((src) => {
            const chunk = src.chunkIndex == null || !chunks ? null : chunks[src.chunkIndex]
            return (
              <li
                key={src.n}
                id={`${idPrefix}source-${src.n}`}
                className={
                  'flex min-w-0 items-baseline gap-2 rounded px-1 py-0.5 ' +
                  (hovered === src.n ? 'bg-accent' : '')
                }
              >
                <span className="w-4 shrink-0 text-right">{src.n}</span>
                <span className="shrink-0 rounded bg-secondary px-1.5 font-mono text-secondary-foreground">
                  {src.domain}
                </span>
                {chunk ? (
                  <button
                    type="button"
                    onClick={() => onOpenPassage?.(src.chunkIndex!)}
                    title="Show this passage"
                    className="flex min-w-0 items-baseline gap-2 text-left hover:text-foreground"
                  >
                    <span className="shrink-0 font-mono text-foreground">{src.ruleId}</span>
                    <span className="shrink-0">{pagesLabel(chunk)}</span>
                    <span className="truncate">· {excerpt(chunk)}</span>
                  </button>
                ) : (
                  <>
                    <span className="shrink-0 font-mono text-foreground">{src.ruleId}</span>
                    {chunks && (
                      <span className="text-amber-700">not in the retrieved passages</span>
                    )}
                  </>
                )}
              </li>
            )
          })}
        </ol>
      )}
    </>
  )
}
