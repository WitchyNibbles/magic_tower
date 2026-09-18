import type { ComponentProps, ReactNode } from 'react'
import { Command as CommandPrimitive } from 'cmdk'
import { SearchIcon } from 'lucide-react'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'

export function CommandDialog({ title, description, open, onOpenChange, children }: { title: string; description: string; open: boolean; onOpenChange: (open: boolean) => void; children: ReactNode }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="overflow-hidden p-0" showCloseButton={false}>
        <DialogTitle className="sr-only">{title}</DialogTitle>
        <DialogDescription className="sr-only">{description}</DialogDescription>
        <CommandPrimitive data-slot="command">{children}</CommandPrimitive>
      </DialogContent>
    </Dialog>
  )
}

export function CommandInput({ className, ...props }: ComponentProps<typeof CommandPrimitive.Input>) {
  return (
    <div className="flex h-11 items-center gap-2 border-b border-border px-3">
      <SearchIcon className="size-4 shrink-0 text-muted-foreground" />
      <CommandPrimitive.Input
        data-slot="command-input"
        className={cn('h-10 w-full bg-transparent py-3 text-sm outline-none placeholder:text-muted-foreground', className)}
        {...props}
      />
    </div>
  )
}

export function CommandList({ className, ...props }: ComponentProps<typeof CommandPrimitive.List>) {
  return <CommandPrimitive.List data-slot="command-list" className={cn('max-h-80 overflow-y-auto overflow-x-hidden p-1', className)} {...props} />
}

export function CommandEmpty(props: ComponentProps<typeof CommandPrimitive.Empty>) {
  return <CommandPrimitive.Empty data-slot="command-empty" className="py-6 text-center text-sm text-muted-foreground" {...props} />
}

export function CommandGroup({ className, ...props }: ComponentProps<typeof CommandPrimitive.Group>) {
  return (
    <CommandPrimitive.Group
      data-slot="command-group"
      className={cn('overflow-hidden p-1 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground', className)}
      {...props}
    />
  )
}

export function CommandItem({ className, ...props }: ComponentProps<typeof CommandPrimitive.Item>) {
  return (
    <CommandPrimitive.Item
      data-slot="command-item"
      className={cn(
        "flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm outline-none select-none data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground [&_svg:not([class*='size-'])]:size-4 [&_svg]:shrink-0 [&_svg]:text-muted-foreground",
        className,
      )}
      {...props}
    />
  )
}
