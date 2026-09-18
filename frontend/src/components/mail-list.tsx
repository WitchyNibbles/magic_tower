import { SearchIcon } from 'lucide-react'
import type { WorkItem } from '@/api'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { sourceLabels, sourceTone, statusLabels, statusTone } from '@/lib/work-items'

export function MailList({ items, selectedId, query, onQuery, onSelect }: {
  items: WorkItem[]
  selectedId: string | null
  query: string
  onQuery: (value: string) => void
  onSelect: (item: WorkItem) => void
}) {
  return (
    <section aria-label="Work queue" className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between gap-3 border-b border-border p-3">
        <div className="relative flex-1">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={query} onChange={e => onQuery(e.target.value)} className="pl-8" placeholder="Search tasks" aria-label="Search tasks" />
        </div>
        <span className="text-xs text-muted-foreground">{items.length} items</span>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto p-2">
        {items.map(item => (
          <button
            key={item.id}
            type="button"
            aria-current={selectedId === item.id}
            onClick={() => onSelect(item)}
            className={cn(
              'flex w-full flex-col gap-1.5 rounded-lg border border-transparent p-3 text-left transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring',
              selectedId === item.id && 'border-border bg-accent',
            )}
          >
            <span className="flex items-center gap-2">
              <span className={cn('size-2 shrink-0 rounded-full', sourceTone[item.source_kind])} />
              <span className="truncate text-sm font-semibold">{item.title}</span>
              <Badge className={cn('ml-auto', statusTone[item.status])}>{statusLabels[item.status]}</Badge>
            </span>
            <span className="line-clamp-2 text-xs text-muted-foreground">{item.summary || 'No summary yet'}</span>
            <span className="text-[0.68rem] tracking-wide text-muted-foreground/80">{sourceLabels[item.source_kind]}</span>
          </button>
        ))}
        {!items.length && <p className="p-8 text-center text-sm text-muted-foreground">No tasks match these filters.</p>}
      </div>
    </section>
  )
}
