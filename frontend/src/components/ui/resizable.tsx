import { GripVerticalIcon } from 'lucide-react'
import { Group, Panel, Separator, type GroupProps, type PanelProps, type SeparatorProps } from 'react-resizable-panels'
import { cn } from '@/lib/utils'

export function ResizablePanelGroup({ className, ...props }: GroupProps) {
  return <Group data-slot="resizable-panel-group" className={cn('flex h-full w-full', className)} {...props} />
}

export function ResizablePanel({ className, ...props }: PanelProps) {
  return <Panel data-slot="resizable-panel" className={cn('flex min-h-0 flex-col', className)} {...props} />
}

export function ResizableHandle({ className, ...props }: SeparatorProps) {
  return (
    <Separator
      data-slot="resizable-handle"
      className={cn('relative flex w-px items-center justify-center bg-border focus-visible:ring-2 focus-visible:ring-ring', className)}
      {...props}
    >
      <span className="z-10 flex h-5 w-3 items-center justify-center rounded-xs border border-border bg-card">
        <GripVerticalIcon className="size-2.5 text-muted-foreground" />
      </span>
    </Separator>
  )
}
