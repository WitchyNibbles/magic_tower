import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'

export function SettingsDialog({ ready, open, onOpenChange }: { ready: boolean; open: boolean; onOpenChange: (open: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogTitle>Your connections</DialogTitle>
        <DialogDescription>Magic Tower only reaches your mailbox once you authorize it.</DialogDescription>
        <div className="flex flex-col gap-2 border-t border-border pt-4">
          <div className="flex items-center justify-between gap-3">
            <b className="text-sm">Microsoft Graph</b>
            <Badge>{ready ? 'Ready' : 'Not connected'}</Badge>
          </div>
          <p className="text-sm text-muted-foreground">{ready ? 'Connected to your local Magic Tower API.' : 'Not connected. Your mail stays private until you explicitly authorize access.'}</p>
        </div>
        <div className="flex flex-col gap-2 border-t border-border pt-4">
          <b className="text-sm">Grimoire</b>
          <p className="text-sm text-muted-foreground">Analyses and the project list are written by grimoire with its own token; Magic Tower never launches an agent.</p>
        </div>
      </DialogContent>
    </Dialog>
  )
}
