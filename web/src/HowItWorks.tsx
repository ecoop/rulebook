// Copyright (c) 2026 Eric Cooper.
//
// "How it works" — a friendly, honest peek under the hood for the curious
// (issue #84). Static content: names the real pipeline and credits Anthropic
// + Voyage AI. Kept accurate over impressive — this is RAG + human-in-the-loop,
// not an agent swarm, and it says so.

import { useEffect } from 'react'

function Section({ n, title, children }: { n: string; title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="mb-1 text-sm font-medium text-foreground">
        <span className="mr-1.5 font-mono text-xs text-muted-foreground">{n}</span>
        {title}
      </h3>
      <p className="text-sm leading-relaxed text-muted-foreground">{children}</p>
    </div>
  )
}

export function HowItWorks({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex justify-center overflow-y-auto bg-black/40 p-4 sm:p-8"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="How Rulebook works"
    >
      <div
        className="my-auto w-full max-w-2xl rounded-xl border border-border bg-card p-6 shadow-lg sm:p-8"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-5 flex items-start justify-between gap-4">
          <h2 className="text-lg font-medium text-foreground">How Rulebook works</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="-mr-1 -mt-1 rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            ✕
          </button>
        </div>

        <div className="space-y-5">
          <p className="text-sm leading-relaxed text-muted-foreground">
            Rulebook answers questions about disc-domain rules with{' '}
            <strong className="font-medium text-foreground">retrieval-augmented generation (RAG)</strong>:
            it looks up the passages of rule text most relevant to your question, then has a language
            model answer using <em>only</em> what it found. Here's the pipeline — and where you can
            watch it work.
          </p>

          <Section n="1" title="Ingestion">
            The rulebooks arrive as PDFs. Ordinary text pages are read directly; image-only pages —
            like the field diagram — are transcribed by Claude's vision model. The text is cleaned
            up and split into short passages (~a few hundred words), each anchored to the rule number
            it came from.
          </Section>

          <Section n="2" title="Retrieval">
            Every passage is turned into a numeric vector (an "embedding") by{' '}
            <strong className="font-medium text-foreground">Voyage AI</strong>. Your question is
            embedded the same way, and the closest passages are pulled. Expand{' '}
            <span className="font-medium text-foreground">"Retrieved passages"</span> under any answer
            to see exactly what was found — the <span className="font-mono text-xs">distance</span> is
            how close each match was (lower is closer).
          </Section>

          <Section n="3" title="Generation">
            <strong className="font-medium text-foreground">Anthropic's Claude</strong> writes the
            answer using only those retrieved passages, and is required to cite each claim inline as{' '}
            <span className="font-mono text-xs">[domain rule_id]</span> — so you can check it against
            the actual rule instead of taking its word for it.
          </Section>

          <Section n="4" title="Human-in-the-loop">
            You rate answers, leave comments, and can author "gold" answers; curators include or
            exclude sources and rebuild the index. That feedback loops back in — improving what gets
            retrieved and how the model answers over time.
          </Section>

          <Section n="—" title="Is it “agentic”?">
            Yes and no. This is a straightforward retrieve-then-generate pipeline, not a system of
            autonomous agents making plans and calling tools. The interesting engineering lives in
            retrieval quality and the human-in-the-loop, not in agent orchestration. There are agents
            in it — Claude transcribes the image-only pages and writes each answer — but they run in a
            fixed, deterministic order rather than one they choose.
          </Section>
        </div>

        <p className="mt-6 border-t border-border pt-4 text-xs text-muted-foreground">
          Generation and diagram vision by{' '}
          <a
            href="https://www.anthropic.com/claude"
            target="_blank"
            rel="noreferrer"
            className="font-medium text-foreground underline decoration-dotted underline-offset-2 hover:text-foreground"
          >
            Anthropic's Claude
          </a>
          ; passage embeddings by{' '}
          <a
            href="https://www.voyageai.com/"
            target="_blank"
            rel="noreferrer"
            className="font-medium text-foreground underline decoration-dotted underline-offset-2 hover:text-foreground"
          >
            Voyage AI
          </a>
          .
        </p>
      </div>
    </div>
  )
}
