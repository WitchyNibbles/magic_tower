import { useState } from 'react'
import { CopyIcon } from 'lucide-react'
import type { WorkItem, WorkStatus } from '@/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { jiraIssueKey, sourceLabels, sourceTone, statusLabels, statuses } from '@/lib/work-items'

export function MailDetail({ item, demo, onStatus, onToast, onHandoff, onDismiss }: {
  item: WorkItem
  demo: boolean
  onStatus: (status: WorkStatus) => void
  onToast: (message: string) => void
  onHandoff: (item: WorkItem, client: 'codex' | 'claude-code') => void
  onDismiss: (item: WorkItem) => void
}) {
  const [agent, setAgent] = useState<'codex' | 'claude-code' | null>(null)
  const command = `scripts/pending-work context ${item.id}`

  const copy = async () => {
    await navigator.clipboard?.writeText(command)
    onToast('Safe context command copied. Paste it into your agent terminal.')
  }

  const chooseAgent = (client: 'codex' | 'claude-code') => {
    setAgent(client)
    if (!demo) onHandoff(item, client)
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto">
      <div className="flex flex-wrap items-center gap-3 border-b border-border p-5">
        <span className={cn('size-2 rounded-full', sourceTone[item.source_kind])} />
        <Badge>{sourceLabels[item.source_kind]}</Badge>
        {jiraIssueKey(item) && (
          <a href={item.source_url ?? undefined} target="_blank" rel="noreferrer" className="text-xs font-semibold text-primary hover:underline">
            {jiraIssueKey(item)}
          </a>
        )}
        {item.assigned_agent && <Badge className="bg-transparent text-muted-foreground">Assigned to {item.assigned_agent}</Badge>}
        <Button size="sm" variant="ghost" className="ml-auto" onClick={() => onDismiss(item)}>Dismiss</Button>
        <label className="text-xs text-muted-foreground">
          Status
          <select
            value={item.status}
            onChange={e => onStatus(e.target.value as WorkStatus)}
            className="ml-2 rounded-md border border-input bg-background px-2 py-1 text-xs font-semibold text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {statuses.map(status => <option key={status} value={status}>{statusLabels[status]}</option>)}
          </select>
        </label>
      </div>

      <div className="flex flex-col gap-6 p-6">
        <div>
          <h2 className="font-serif text-2xl leading-tight tracking-tight">{item.title}</h2>
          <p className="mt-2 leading-relaxed text-muted-foreground">{item.summary || 'No summary was added to this task.'}</p>
        </div>

        <section className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold">Why this is here <span className="font-normal text-muted-foreground">Source evidence</span></h3>
          {item.evidence?.length
            ? item.evidence.map((entry, index) => (
              <blockquote key={index} className="rounded-r-md border-l-2 border-primary bg-muted px-4 py-3 text-sm leading-relaxed">
                {entry.excerpt}
                <footer className="mt-2 text-xs text-muted-foreground">{sourceLabels[entry.source_kind]} conversation</footer>
              </blockquote>
            ))
            : <p className="rounded-md bg-muted p-4 text-sm text-muted-foreground">This task was added manually, so no message evidence is available.</p>}
        </section>

        <section className="flex flex-col gap-2 rounded-xl border border-border bg-card p-5">
          <p className="text-xs font-semibold tracking-[0.16em] text-primary">AGENT HANDOFF</p>
          <h3 className="text-sm font-semibold">Invite an agent to take this on</h3>
          <p className="text-sm leading-relaxed text-muted-foreground">Magic Tower records a bounded handoff and copies only the task ID. It never puts mailbox text in a shell command.</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button size="sm" onClick={() => chooseAgent('codex')}>Use Codex</Button>
            <Button size="sm" variant="secondary" onClick={() => chooseAgent('claude-code')}>Use Claude Code</Button>
          </div>
          {agent && (
            <div className="mt-3 flex flex-wrap items-center gap-3 rounded-md border border-input bg-background p-3">
              <code className="flex-1 overflow-auto text-xs">{command}</code>
              <Button size="sm" variant="secondary" onClick={copy}><CopyIcon />Copy command</Button>
              {demo && <small className="w-full text-xs text-muted-foreground">Sample item only — nothing will be dispatched.</small>}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
