import type { WorkItem } from '@/api'
import { sourceLabels } from '@/lib/work-items'

interface TriageGroup {
  key: string
  label: string
  items: WorkItem[]
}

const replyPrefix = /^\s*(?:re|fwd?)\s*(?:\[\d+\])?\s*:\s*/i

const noSubject = '(no subject)'

const threadOf = (title: string) => {
  let subject = title
  while (replyPrefix.test(subject)) subject = subject.replace(replyPrefix, '')
  return subject.trim().replace(/\s+/g, ' ') || noSubject
}

/**
 * Group work items for triage, by source kind and then by thread.
 *
 * The rules, in order, are deterministic — no fuzzy matching and no model call:
 * 1. Two items share a group only when their source kinds are equal, so an
 *    Outlook mail and a Teams message with the same subject stay apart.
 * 2. Within one source kind, the thread is the title with leading reply and
 *    forward markers ("Re:", "FW:", "Fwd:", "RE[2]:") stripped as often as they
 *    repeat, trimmed, inner whitespace collapsed, matched case-insensitively.
 *    A title that is only markers (or blank) threads as "(no subject)".
 * 3. Groups come back in the order their first item appears in `items`, and each
 *    group keeps its items in that order, so equal input always renders equally.
 *
 * The label shows the first spelling of the thread that arrived, not the reply.
 */
export function groupForTriage(items: WorkItem[]): TriageGroup[] {
  const groups = new Map<string, TriageGroup>()
  for (const item of items) {
    const thread = threadOf(item.title)
    const key = `${item.source_kind}:${thread.toLowerCase()}`
    const seen = groups.get(key)
    groups.set(key, seen
      ? { ...seen, items: [...seen.items, item] }
      : { key, label: `${sourceLabels[item.source_kind]} · ${thread}`, items: [item] })
  }
  return [...groups.values()]
}
