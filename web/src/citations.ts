// Copyright (c) 2026 Eric Cooper.
// Footnote citations: the answer's [domain rule_id] brackets become numbered
// markers, and each cited source is listed once, under the answer.
//
// Parsing mirrors the backend's find_unverified_citations (src/rulebook/
// generate.py) so the two agree on what a citation is and which passage it
// points to: a bracket names a domain and one or more rule ids, an optional
// page suffix is ignored, and a sub-clause (II.B.1.a, R2(f)(i)) points into the
// passage of the rule it sits under.

export interface CitableChunk {
  text: string
  domain: string
  rule_id: string
  page_start: number
  page_end: number
}

export interface Source {
  n: number
  domain: string
  ruleId: string
  // Index into the chunks the answer was given; null when the citation matches
  // none of them (the backend lists these as unverified_citations).
  chunkIndex: number | null
}

export type Segment = { kind: 'text'; text: string } | { kind: 'cite'; ns: number[] }

export interface FootnotedAnswer {
  segments: Segment[]
  sources: Source[]
}

const CITATION_RE = /\[([a-z][a-z0-9_-]*)\s+([^\]]+)\]/g
const DOMAIN_PREFIX_RE = /^([a-z][a-z0-9_-]*)\s+(\S.*)$/
// " — p.7", " — pp.65-70", or the same without the dash (" pp.65-70").
const PAGE_SUFFIX_RE = /\s*(?:—\s*)?pp?\.\s?\d+(?:\s*[-–]\s*\d+)?\s*$/

function bracketCitations(domain: string, rest: string): [string, string][] {
  const pairs: [string, string][] = []
  rest
    .trim()
    .split(/\s*[,;]\s*/)
    .forEach((item, i) => {
      let itemDomain = domain
      const m = i > 0 ? DOMAIN_PREFIX_RE.exec(item) : null
      if (m) {
        itemDomain = m[1]
        item = m[2]
      }
      const ruleId = item.split(' — ')[0].replace(PAGE_SUFFIX_RE, '').trim()
      if (ruleId) pairs.push([itemDomain, ruleId])
    })
  return pairs
}

// The chunk a citation points to: the same rule, or the closest rule it is a
// sub-clause of (continuing the id with "." or "(").
export function matchChunk(domain: string, ruleId: string, chunks: CitableChunk[]): number | null {
  let best: number | null = null
  let bestLen = -1
  chunks.forEach((c, i) => {
    if (c.domain !== domain) return
    const parent = c.rule_id.trim()
    const covers =
      parent === ruleId ||
      (ruleId.length > parent.length &&
        ruleId.startsWith(parent) &&
        '.('.includes(ruleId[parent.length]))
    if (covers && parent.length > bestLen) {
      best = i
      bestLen = parent.length
    }
  })
  return best
}

export function footnoteCitations(
  answer: string,
  chunks: CitableChunk[],
  unverified: string[] = [],
): FootnotedAnswer {
  const domains = new Set(chunks.map((c) => c.domain))
  const flagged = new Set(unverified)
  const sources: Source[] = []
  const byLabel = new Map<string, number>()
  const segments: Segment[] = []

  const number = (domain: string, ruleId: string): number => {
    const label = `${domain} ${ruleId}`
    let n = byLabel.get(label)
    if (n === undefined) {
      n = sources.length + 1
      byLabel.set(label, n)
      sources.push({ n, domain, ruleId, chunkIndex: matchChunk(domain, ruleId, chunks) })
    }
    return n
  }

  let last = 0
  for (const m of answer.matchAll(CITATION_RE)) {
    const start = m.index ?? 0
    const end = start + m[0].length
    if (answer[end] === '(') continue // a Markdown link, not a citation
    const pairs = bracketCitations(m[1], m[2])
    // Only brackets that name a domain in play, or that the backend flagged,
    // are citations; anything else ("[sic]") stays as written.
    const isCitation = pairs.some(
      ([d, r]) => domains.has(d) || flagged.has(`${d} ${r}`),
    )
    if (!isCitation) continue
    const ns = pairs.map(([d, r]) => number(d, r))
    // The marker sits against the word before it: drop the space the model
    // puts before a bracket.
    const before = answer.slice(last, start).replace(/[ \t]+$/, '')
    const prev = segments[segments.length - 1]
    if (before === '' && prev?.kind === 'cite') {
      prev.ns.push(...ns) // [a][b] with nothing between: one marker, "1, 2"
    } else {
      if (before) segments.push({ kind: 'text', text: before })
      segments.push({ kind: 'cite', ns })
    }
    last = end
  }
  if (last < answer.length) segments.push({ kind: 'text', text: answer.slice(last) })
  for (const s of segments) {
    if (s.kind === 'cite') s.ns = [...new Set(s.ns)].sort((a, b) => a - b)
  }
  return { segments, sources }
}

// A passage's opening words, about one line: the rule id it starts with is
// dropped (the row already shows it) and the cut falls at a word boundary.
export function excerpt(chunk: CitableChunk, max = 70): string {
  let text = chunk.text.replace(/\s+/g, ' ').trim()
  const id = chunk.rule_id.trim()
  if (text.startsWith(id)) text = text.slice(id.length).replace(/^[.:\s]+/, '')
  if (text.length <= max) return text
  const cut = text.lastIndexOf(' ', max)
  return text.slice(0, cut > max / 2 ? cut : max).replace(/[\s,;:.]+$/, '') + '…'
}

export function pagesLabel(chunk: Pick<CitableChunk, 'page_start' | 'page_end'>): string {
  if (chunk.page_start === 0 && chunk.page_end === 0) return ''
  return chunk.page_start === chunk.page_end
    ? `p.${chunk.page_start}`
    : `pp.${chunk.page_start}-${chunk.page_end}`
}
