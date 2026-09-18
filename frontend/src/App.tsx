import { useEffect, useMemo, useState } from 'react'
import { SearchIcon, SettingsIcon, XIcon } from 'lucide-react'
import { ApiError, beginMicrosoftConnect, createDispatch, dismissWorkItem, getHealth, getSources, getWorkItem, getWorkItems, promoteSource, restoreLocalSession, startLocalSession, syncNow, updateWorkItem, type Source, type SourceKind, type WorkItem, type WorkStatus } from './api'
import { CommandPalette } from '@/components/command-palette'
import { MailDetail } from '@/components/mail-detail'
import { MailList } from '@/components/mail-list'
import { MailNav } from '@/components/mail-nav'
import { SettingsDialog } from '@/components/settings-dialog'
import { UnlockPanel } from '@/components/unlock-panel'
import { Button } from '@/components/ui/button'
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable'
import { demoItems } from '@/lib/work-items'

const PAGE_LIMIT = 50

export default function App() {
  const [items, setItems] = useState<WorkItem[]>([])
  const [selected, setSelected] = useState<WorkItem | null>(null)
  const [filter, setFilter] = useState<WorkStatus | 'all'>('all')
  const [source, setSource] = useState<SourceKind | 'all'>('all')
  const [query, setQuery] = useState('')
  const [state, setState] = useState<'checking' | 'ready' | 'offline'>('checking')
  const [demo, setDemo] = useState(false)
  const [settings, setSettings] = useState(false)
  const [palette, setPalette] = useState(false)
  const [toast, setToast] = useState('')
  const [locked, setLocked] = useState(false)
  const [remoteTotal, setRemoteTotal] = useState(0)
  const [loadedCount, setLoadedCount] = useState(0)
  const [loadingMore, setLoadingMore] = useState(false)
  const [missed, setMissed] = useState<Source[]>([])

  const loadMissed = async (loadedItems: WorkItem[]) => {
    try {
      const page = await getSources({ limit: 200 })
      const promoted = new Set(loadedItems.map(i => i.source_external_id).filter((id): id is string => Boolean(id)))
      setMissed((page.items ?? []).filter(candidate => !promoted.has(candidate.external_id)))
    } catch { setMissed([]) }
  }

  const loadWork = async () => {
    try {
      await getHealth()
      await restoreLocalSession()
      const page = await getWorkItems()
      const work = page.items.filter(i => i.status !== 'dismissed')
      setState('ready'); setLocked(false); setDemo(false)
      setItems(work); setSelected(work[0] ?? null)
      setRemoteTotal(page.total); setLoadedCount(page.items.length)
      void loadMissed(work)
    } catch (error) {
      if (error instanceof ApiError && (error.status === 401 || error.status === 503)) { setState('offline'); setLocked(true); return }
      setState('offline'); setDemo(true); setItems(demoItems); setSelected(demoItems[0])
      setRemoteTotal(demoItems.length); setLoadedCount(demoItems.length); setMissed([])
    }
  }

  const loadMore = async () => {
    setLoadingMore(true)
    try {
      const page = await getWorkItems({ limit: PAGE_LIMIT, offset: loadedCount })
      const additions = page.items.filter(i => i.status !== 'dismissed')
      setItems(all => [...all, ...additions]); setRemoteTotal(page.total); setLoadedCount(count => count + page.items.length)
    } catch { setToast('Could not load more items.') }
    finally { setLoadingMore(false) }
  }

  useEffect(() => { void loadWork() }, [])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === 'k' && (event.metaKey || event.ctrlKey)) { event.preventDefault(); setPalette(open => !open) }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  const unlock = async (token: string) => {
    try { await startLocalSession(token); await loadWork() } catch { setToast('That local token could not unlock Magic Tower.') }
  }
  const connectMicrosoft = async () => {
    try { await beginMicrosoftConnect() } catch { setToast('Microsoft connection could not start.') }
  }
  const runSync = async () => {
    try { const result = await syncNow(); await loadWork(); setToast(result.detail || 'Microsoft messages synced.') } catch { setToast('Sync could not be completed.') }
  }
  const handoff = async (item: WorkItem, client: 'codex' | 'claude-code') => {
    try { await createDispatch(item.id, client, 'Review the local Magic Tower item and propose the next safe action.'); setToast(`Queued a ${client} handoff.`) } catch { setToast('Could not queue the agent handoff.') }
  }
  const showDemo = () => {
    setDemo(true); setItems(demoItems); setSelected(demoItems[0]); setToast('Showing sample items — connect the API for your work queue.')
  }
  const choose = async (item: WorkItem) => {
    setSelected(item)
    if (!demo) try { setSelected(await getWorkItem(item.id)) } catch { /* list summary remains usable */ }
  }
  const changeStatus = async (status: WorkStatus) => {
    if (!selected) return
    const old = selected
    const next = { ...old, status }
    setSelected(next); setItems(all => all.map(i => i.id === next.id ? next : i))
    if (!demo) try {
      const saved = await updateWorkItem(old.id, { status })
      setSelected(saved); setItems(all => all.map(i => i.id === saved.id ? saved : i))
    } catch {
      setSelected(old); setItems(all => all.map(i => i.id === old.id ? old : i)); setToast('Could not save that change.')
    }
  }
  const dismiss = async (item: WorkItem) => {
    // Dismissing moves a row to the 'dismissed' status rather than deleting it, so the server's
    // unfiltered total is unchanged — decrementing it here would strand the still-unfetched pages.
    setItems(all => all.filter(i => i.id !== item.id))
    setSelected(current => current?.id === item.id ? null : current)
    if (demo) { setToast('Dismissed the sample item.'); return }
    try { await dismissWorkItem(item.id); setToast('Dismissed. It will stay out of the queue.') }
    catch {
      setItems(all => [item, ...all]); setSelected(item)
      setToast('Could not dismiss that item.')
    }
  }
  const promote = async (candidate: Source) => {
    try {
      const created = await promoteSource(candidate.id)
      setMissed(all => all.filter(s => s.id !== candidate.id))
      setItems(all => [created, ...all]); setSelected(created); setRemoteTotal(t => t + 1)
      setToast('Promoted to your work queue.')
    } catch { setToast('Could not promote that source.') }
  }

  const visible = useMemo(
    () => items.filter(i => (filter === 'all' || i.status === filter) && (source === 'all' || i.source_kind === source) && `${i.title} ${i.summary ?? ''}`.toLowerCase().includes(query.toLowerCase())),
    [items, filter, source, query],
  )

  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-2.5">
        <div className="flex items-center gap-3">
          <img src="/magic-tower-logo.png" alt="Magic Tower" className="size-8 object-contain" />
          <div>
            <h1 className="font-serif text-base leading-tight">Magic Tower</h1>
            <p className="text-[0.68rem] text-muted-foreground">A private task grimoire</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => setPalette(true)}>
            <SearchIcon />Search
            <kbd className="ml-2 rounded-sm bg-secondary px-1.5 py-0.5 text-[0.65rem] text-muted-foreground">⌘K</kbd>
          </Button>
          <span className={state === 'ready' ? 'text-xs text-emerald-300' : 'text-xs text-muted-foreground'}>
            {state === 'ready' ? '● Synced locally' : state === 'checking' ? 'Reading the stars' : '● Offline'}
          </span>
          <Button variant="ghost" size="icon" onClick={() => setSettings(true)} aria-label="Settings"><SettingsIcon /></Button>
        </div>
      </header>

      <ResizablePanelGroup orientation="horizontal" className="min-h-0 flex-1">
        <ResizablePanel defaultSize="19" minSize="14">
          <MailNav items={items} filter={filter} onFilter={setFilter} source={source} onSource={setSource} onSync={runSync} onConnect={connectMicrosoft} onDemo={showDemo} missed={missed} onPromote={promote} />
        </ResizablePanel>
        <ResizableHandle />
        <ResizablePanel defaultSize="33" minSize="22" className="bg-card/40">
          <MailList items={visible} total={items.length} selectedId={selected?.id ?? null} query={query} onQuery={setQuery} onSelect={choose}
            hasMore={!demo && loadedCount < remoteTotal} loadingMore={loadingMore} onLoadMore={loadMore} />
        </ResizablePanel>
        <ResizableHandle />
        <ResizablePanel defaultSize="48" minSize="30">
          <section aria-label="Work item detail" className="flex h-full min-h-0 flex-col bg-card/60">
            {selected
              ? <MailDetail item={selected} demo={demo} onStatus={changeStatus} onToast={setToast} onHandoff={handoff} onDismiss={dismiss} />
              : locked
                ? <UnlockPanel onUnlock={unlock} />
                : <div className="m-auto max-w-sm p-8 text-center">
                    <h2 className="font-serif text-xl">Your tower is quiet.</h2>
                    <p className="mt-2 text-sm text-muted-foreground">Connect Microsoft Graph or explore the sample queue.</p>
                    <Button className="mt-4" onClick={showDemo}>Explore sample tasks</Button>
                  </div>}
          </section>
        </ResizablePanel>
      </ResizablePanelGroup>

      {toast && (
        <div className="fixed top-4 left-1/2 z-[60] flex -translate-x-1/2 items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-semibold text-primary-foreground shadow-xl">
          {toast}
          <Button variant="ghost" size="icon" className="size-5 text-primary-foreground hover:bg-primary-foreground/10" onClick={() => setToast('')} aria-label="Dismiss notification"><XIcon /></Button>
        </div>
      )}

      <CommandPalette open={palette} onOpenChange={setPalette} items={items} onSelect={choose} onSync={runSync} onConnect={connectMicrosoft} onDemo={showDemo} onSettings={() => setSettings(true)} />
      <SettingsDialog ready={state === 'ready'} open={settings} onOpenChange={setSettings} />
    </div>
  )
}
