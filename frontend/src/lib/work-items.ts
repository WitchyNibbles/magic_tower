import type { SourceKind, WorkItem, WorkStatus } from '@/api'

// Filterable/editable statuses — 'dismissed' is deliberately excluded: it is reached only
// through the dismiss action (B51), never picked from a filter or a status dropdown.
export const statuses: WorkStatus[] = ['pending', 'in_progress', 'blocked', 'done']
export const statusLabels: Record<WorkStatus, string> = { pending: 'To do', in_progress: 'In progress', blocked: 'Blocked', done: 'Done', dismissed: 'Dismissed' }
export const sourceLabels: Record<SourceKind, string> = { outlook_email: 'Outlook', manual: 'Manual', jira: 'Jira' }

export const statusTone: Record<WorkStatus, string> = {
  pending: 'bg-secondary text-secondary-foreground',
  in_progress: 'bg-sky-500/15 text-sky-200',
  blocked: 'bg-destructive/15 text-destructive',
  done: 'bg-emerald-500/15 text-emerald-200',
  dismissed: 'bg-muted text-muted-foreground',
}

export const sourceTone: Record<SourceKind, string> = {
  outlook_email: 'bg-sky-400',
  manual: 'bg-muted-foreground',
  jira: 'bg-indigo-400',
}

// The `.../browse/{KEY}` path segment jira_sync.py's `_normalize_issue` builds `source_url`
// from. The backend does persist the key as its own field — `work_item_issue_keys.issue_key`,
// added so one issue cannot become two work items — but no API response exposes it: a work item
// arrives carrying `source_url` and a `source_external_id` of `jira:{numeric id}`, never the key.
// So the URL is the only place the browser can read it back.
export const jiraIssueKey = (item: Pick<WorkItem, 'source_kind' | 'source_url'>): string | null => {
  if (item.source_kind !== 'jira' || !item.source_url) return null
  return item.source_url.match(/\/browse\/([^/?#]+)/)?.[1] ?? null
}

export const demoItems: WorkItem[] = [
  { id: 'demo-email', title: 'Send the revised project estimate', summary: 'The client asked for an updated estimate before Friday.', status: 'pending', source_kind: 'outlook_email', source_external_id: 'demo-001', source_url: null, assigned_agent: null, due_at: null, created_at: '', updated_at: '', evidence: [{ source_kind: 'outlook_email', external_id: 'demo-001', excerpt: 'Could you send the revised estimate before Friday?', observed_at: '' }] },
  { id: 'demo-rollout', title: 'Confirm the rollout owner', summary: 'A decision is needed before the launch goes out.', status: 'blocked', source_kind: 'manual', source_external_id: null, source_url: null, assigned_agent: 'Codex', due_at: null, created_at: '', updated_at: '', evidence: [] },
  { id: 'demo-manual', title: 'Review next week’s priorities', summary: 'Prepare the work plan for the team check-in.', status: 'in_progress', source_kind: 'manual', source_external_id: null, source_url: null, assigned_agent: null, due_at: null, created_at: '', updated_at: '', evidence: [] },
]
