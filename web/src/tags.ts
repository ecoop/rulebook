// Copyright (c) 2026 Eric Cooper.
//
// Issue tags — a small, action-oriented taxonomy. Multi-select. The point
// isn't to fully classify every answer; it's to separate failure modes that
// need different downstream fixes (correction vs corpus augmentation vs
// retrieval tuning vs prompt tuning). Shared by the main-page feedback form
// and the "Your activity" rate/edit editors so the vocabulary stays in sync.

export type IssueTag = 'wrong' | 'incomplete' | 'retrieval' | 'format'

export const TAG_LABELS: Record<IssueTag, string> = {
  wrong: 'wrong facts — needs correction',
  incomplete: 'missing context — corpus needs more info',
  retrieval: 'wrong passages retrieved — retrieval quality issue',
  format: 'facts right, delivery off — prompt tuning',
}

export const TAGS: IssueTag[] = ['wrong', 'incomplete', 'retrieval', 'format']
