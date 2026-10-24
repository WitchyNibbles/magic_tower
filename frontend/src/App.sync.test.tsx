import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import App from './App'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

type Call = { path: string; init?: RequestInit }

// `sync` is the /api/sync/all reply; a function lets a test make the request fail.
const stubApi = (sync: () => object | Promise<object>) => {
  const calls: Call[] = []
  vi.stubGlobal('fetch', vi.fn(async (path: string, init?: RequestInit) => {
    calls.push({ path, init })
    const body = path === '/api/sync/all' ? await sync()
      : path === '/api/work-items' ? { items: [], total: 0, limit: 50, offset: 0 }
      : path === '/api/session' ? { csrf_token: 'csrf-test' }
      : path === '/api/sources' || path.startsWith('/api/sources?') ? { items: [], total: 0, limit: 200, offset: 0 }
      : { status: 'ok', service: 'workboard' }
    return { ok: true, status: 200, json: async () => body }
  }))
  return calls
}

const pressSync = async () => fireEvent.click(await screen.findByRole('button', { name: /Sync now/ }))

describe('Sync now', () => {
  it('posts to /api/sync/all with the CSRF header', async () => {
    const calls = stubApi(() => ({ results: {} }))

    render(<App />)
    await pressSync()

    await waitFor(() => expect(calls.some(c => c.path === '/api/sync/all')).toBe(true))
    const sync = calls.find(c => c.path === '/api/sync/all')!
    expect(sync.init?.method).toBe('POST')
    expect((sync.init?.headers as Record<string, string>)['X-CSRF-Token']).toBe('csrf-test')
  })

  it('names each source in the toast, with counts or its error', async () => {
    stubApi(() => ({ results: {
      jira: { count: 5, new_sources: 2, new_work_items: 2, mode: 'jira', synced_at: '2026-10-24T10:00:00Z', window_minutes: 20160 },
      graph: { error: 'Microsoft Graph is not connected' },
    } }))

    render(<App />)
    await pressSync()

    expect(await screen.findByText('Jira: 2 new items. Outlook: Microsoft Graph is not connected')).toBeTruthy()
  })

  it('says so when a source found nothing new, and keeps unknown kinds under their raw name', async () => {
    stubApi(() => ({ results: {
      jira: { count: 3, new_sources: 0, new_work_items: 1 },
      graph: { count: 0, new_sources: 0, new_work_items: 0 },
      zendesk: { count: 0, new_sources: 0, new_work_items: 0 },
    } }))

    render(<App />)
    await pressSync()

    expect(await screen.findByText('Jira: 1 new item. Outlook: no new items. zendesk: no new items')).toBeTruthy()
  })

  it('labels the Freshservice result by its name, not its raw kind', async () => {
    stubApi(() => ({ results: {
      freshservice: { count: 4, new_sources: 4, new_work_items: 2 },
    } }))

    render(<App />)
    await pressSync()

    expect(await screen.findByText('Freshservice: 2 new items')).toBeTruthy()
  })

  it('points the owner to Jira and Outlook setup when nothing is configured', async () => {
    stubApi(() => ({ results: {} }))

    render(<App />)
    await pressSync()

    expect(await screen.findByText('Nothing to sync yet. Set up Jira or connect Outlook.')).toBeTruthy()
  })

  it('keeps the generic message when the request fails', async () => {
    stubApi(() => { throw new Error('network down') })

    render(<App />)
    await pressSync()

    expect(await screen.findByText('Sync could not be completed.')).toBeTruthy()
  })

  it('reloads the work list after a sync', async () => {
    const calls = stubApi(() => ({ results: { jira: { count: 1, new_sources: 1, new_work_items: 1 } } }))

    render(<App />)
    await screen.findByRole('button', { name: /Sync now/ })
    await waitFor(() => expect(calls.filter(c => c.path === '/api/work-items').length).toBe(1))
    await pressSync()

    await waitFor(() => expect(calls.filter(c => c.path === '/api/work-items').length).toBe(2))
  })
})
