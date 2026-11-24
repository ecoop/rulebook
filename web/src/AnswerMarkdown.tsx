// Copyright (c) 2026 Eric Cooper.
// The answer rendered as Markdown (the model writes lists and bold), with each
// footnote marker as a superscript. Loaded lazily from App.tsx: the Markdown
// parser is most of its weight, and no answer exists until a question returns.
import { useMemo } from 'react'
import Markdown, { type Components } from 'react-markdown'
import { citeNumbers } from './citations'

export default function AnswerMarkdown({
  markdown,
  onHover,
}: {
  markdown: string
  onHover: (n: number | null) => void
}) {
  const components = useMemo<Components>(
    () => ({
      a: ({ href, children }) => {
        const ns = citeNumbers(href)
        if (!ns) {
          return (
            <a href={href} target="_blank" rel="noreferrer" className="underline">
              {children}
            </a>
          )
        }
        return (
          <sup className="ml-px text-[0.7rem] text-muted-foreground">
            {ns.map((n, j) => (
              <span key={n}>
                {j > 0 && ', '}
                <a
                  href={`#source-${n}`}
                  onMouseEnter={() => onHover(n)}
                  onMouseLeave={() => onHover(null)}
                  className="hover:text-foreground"
                >
                  {n}
                </a>
              </span>
            ))}
          </sup>
        )
      },
      p: ({ children }) => <p className="mb-3 last:mb-0">{children}</p>,
      ul: ({ children }) => <ul className="mb-3 list-disc space-y-1 pl-5 last:mb-0">{children}</ul>,
      ol: ({ children }) => <ol className="mb-3 list-decimal space-y-1 pl-5 last:mb-0">{children}</ol>,
      strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
      // Headings stay at the answer's own size, in bold.
      h1: ({ children }) => <p className="mb-1 mt-4 font-semibold first:mt-0">{children}</p>,
      h2: ({ children }) => <p className="mb-1 mt-4 font-semibold first:mt-0">{children}</p>,
      h3: ({ children }) => <p className="mb-1 mt-4 font-semibold first:mt-0">{children}</p>,
      h4: ({ children }) => <p className="mb-1 mt-4 font-semibold first:mt-0">{children}</p>,
      code: ({ children }) => (
        <code className="rounded bg-secondary px-1 font-mono text-[0.8rem]">{children}</code>
      ),
    }),
    [onHover],
  )
  return <Markdown components={components}>{markdown}</Markdown>
}
