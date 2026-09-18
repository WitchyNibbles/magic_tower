import { LinkIcon, RefreshCwIcon, SettingsIcon, SparklesIcon } from 'lucide-react'
import type { WorkItem } from '@/api'
import { CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { sourceLabels } from '@/lib/work-items'

export function CommandPalette({ open, onOpenChange, items, onSelect, onSync, onConnect, onDemo, onSettings }: {
  open: boolean
  onOpenChange: (open: boolean) => void
  items: WorkItem[]
  onSelect: (item: WorkItem) => void
  onSync: () => void
  onConnect: () => void
  onDemo: () => void
  onSettings: () => void
}) {
  const run = (action: () => void) => () => {
    onOpenChange(false)
    action()
  }

  return (
    <CommandDialog title="Command palette" description="Search work items and run Magic Tower actions." open={open} onOpenChange={onOpenChange}>
      <CommandInput placeholder="Search work items or run a command…" />
      <CommandList>
        <CommandEmpty>Nothing matches that search.</CommandEmpty>
        <CommandGroup heading="Work items">
          {items.map(item => (
            <CommandItem key={item.id} value={`${item.title} ${item.summary ?? ''}`} onSelect={run(() => onSelect(item))}>
              <span className="truncate">{item.title}</span>
              <span className="ml-auto shrink-0 text-xs text-muted-foreground">{sourceLabels[item.source_kind]}</span>
            </CommandItem>
          ))}
        </CommandGroup>
        <CommandGroup heading="Actions">
          <CommandItem value="Sync now" onSelect={run(onSync)}><RefreshCwIcon />Sync now</CommandItem>
          <CommandItem value="Connect Microsoft" onSelect={run(onConnect)}><LinkIcon />Connect Microsoft</CommandItem>
          <CommandItem value="View sample queue" onSelect={run(onDemo)}><SparklesIcon />View sample</CommandItem>
          <CommandItem value="Open settings" onSelect={run(onSettings)}><SettingsIcon />Settings</CommandItem>
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  )
}
