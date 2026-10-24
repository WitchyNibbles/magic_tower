import type { WorkItem, WorkStatus } from '@/api'
import { AnalysisDetails, AnalysisSummary } from '@/components/analysis-panel'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { itemSummary, jiraIssueKey, sourceLabels, sourceTone, statusLabels, statuses } from '@/lib/work-items'

export function MailDetail({ item, onStatus, onDismiss }: {
  item: WorkItem
  onStatus: (status: WorkStatus) => void
  onDismiss: (item: WorkItem) => void
}) {
  const analysis = item.analysis
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
          {analysis
            ? <AnalysisSummary analysis={analysis} />
            : <>
                <p className="mt-2 leading-relaxed text-muted-foreground">{itemSummary(item) || 'No summary was added to this task.'}</p>
                <p className="mt-2 text-xs text-muted-foreground">No analysis yet.</p>
              </>}
        </div>

        {analysis && <AnalysisDetails analysis={analysis} />}

        <section className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold">Why this is here <span className="font-normal text-muted-foreground">Source evidence</span></h3>
          {item.evidence?.length
            ? item.evidence.map((entry, index) => entry.excerpt
              ? (
                <blockquote key={index} className="rounded-r-md border-l-2 border-primary bg-muted px-4 py-3 text-sm leading-relaxed">
                  {entry.excerpt}
                  <footer className="mt-2 text-xs text-muted-foreground">{sourceLabels[entry.source_kind]} conversation</footer>
                </blockquote>
              )
              : <p key={index} className="text-xs text-muted-foreground">{sourceLabels[entry.source_kind]} conversation</p>)
            : <p className="rounded-md bg-muted p-4 text-sm text-muted-foreground">This task was added manually, so no message evidence is available.</p>}
        </section>
      </div>
    </div>
  )
}
