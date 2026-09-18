import { InboxIcon, LinkIcon, RefreshCwIcon, SparklesIcon } from 'lucide-react'
import type { Source, SourceKind, WorkItem, WorkStatus } from '@/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { sourceLabels, statusLabels, statuses } from '@/lib/work-items'

const sources: (SourceKind | 'all')[] = ['all', 'outlook_email', 'teams_message', 'manual']

export function MailNav({ items, filter, onFilter, source, onSource, onSync, onConnect, onDemo, missed, onPromote }: {
  items: WorkItem[]
  filter: WorkStatus | 'all'
  onFilter: (value: WorkStatus | 'all') => void
  source: SourceKind | 'all'
  onSource: (value: SourceKind | 'all') => void
  onSync: () => void
  onConnect: () => void
  onDemo: () => void
  missed: Source[]
  onPromote: (source: Source) => void
}) {
  const count = (status: WorkStatus | 'all') => (status === 'all' ? items.length : items.filter(i => i.status === status).length)

  return (
    <section aria-label="Filters" className="flex h-full min-h-0 flex-col gap-4 overflow-y-auto p-3">
      <nav className="flex flex-col gap-1">
        {(['all', ...statuses] as const).map(status => (
          <Button
            key={status}
            variant={filter === status ? 'secondary' : 'ghost'}
            size="sm"
            className="justify-start"
            aria-pressed={filter === status}
            onClick={() => onFilter(status)}
          >
            <InboxIcon />
            <span className="flex-1 text-left">{status === 'all' ? 'All work' : statusLabels[status]}</span>
            <Badge className="bg-transparent px-0 text-muted-foreground">{count(status)}</Badge>
          </Button>
        ))}
      </nav>

      <div className="flex flex-col gap-1 border-t border-border pt-4">
        <p className="px-3 pb-1 text-xs font-semibold tracking-[0.16em] text-primary">SOURCES</p>
        {sources.map(kind => (
          <Button
            key={kind}
            variant={source === kind ? 'secondary' : 'ghost'}
            size="sm"
            className="justify-start"
            aria-pressed={source === kind}
            onClick={() => onSource(kind)}
          >
            <span className={cn('size-2 rounded-full', kind === 'all' ? 'bg-primary' : kind === 'outlook_email' ? 'bg-sky-400' : kind === 'teams_message' ? 'bg-violet-400' : 'bg-muted-foreground')} />
            {kind === 'all' ? 'All sources' : sourceLabels[kind]}
          </Button>
        ))}
      </div>

      {missed.length > 0 && (
        <div role="group" aria-label="Missed sources" className="flex flex-col gap-1 border-t border-border pt-4">
          <p className="px-3 pb-1 text-xs font-semibold tracking-[0.16em] text-primary">MISSED</p>
          {missed.map(candidate => (
            <div key={candidate.id} className="flex items-center gap-2 px-3">
              <span className="flex-1 truncate text-xs text-muted-foreground">{candidate.subject || '(no subject)'}</span>
              <Button size="sm" variant="ghost" onClick={() => onPromote(candidate)}>Promote</Button>
            </div>
          ))}
        </div>
      )}

      <div className="mt-auto flex flex-col gap-2 border-t border-border pt-4">
        <Button variant="outline" size="sm" onClick={onSync}><RefreshCwIcon />Sync now</Button>
        <Button variant="outline" size="sm" onClick={onConnect}><LinkIcon />Connect Microsoft</Button>
        <Button variant="ghost" size="sm" onClick={onDemo}><SparklesIcon />View sample</Button>
      </div>
    </section>
  )
}
