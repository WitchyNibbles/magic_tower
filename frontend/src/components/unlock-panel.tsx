import { useState, type FormEvent } from 'react'
import { LockIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

export function UnlockPanel({ onUnlock }: { onUnlock: (token: string) => Promise<void> }) {
  const [token, setToken] = useState('')

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    await onUnlock(token)
    setToken('')
  }

  return (
    <form onSubmit={submit} className="m-auto flex w-full max-w-sm flex-col gap-3 rounded-xl border border-border bg-card p-6">
      <LockIcon className="size-5 text-primary" />
      <h2 className="font-serif text-xl">Unlock Magic Tower</h2>
      <label htmlFor="local-token" className="text-xs text-muted-foreground">Local API token</label>
      <Input id="local-token" type="password" value={token} onChange={e => setToken(e.target.value)} autoComplete="off" required />
      <p className="text-xs text-muted-foreground">Used for this browser session only. It is never saved.</p>
      <Button type="submit">Unlock</Button>
    </form>
  )
}
