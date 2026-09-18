import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import App from './App'
import type { Source, WorkItem } from './api'
import { demoItems } from '@/lib/work-items'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const item = (id: string, title: string, rest: Partial<WorkItem> = {}): WorkItem => ({
  id, title, summary: null, status: 'pending', source_kind: 'outlook_email', source_external_id: `outlook_email:${id}`,
  source_url: null, assigned_agent: null, due_at: null, created_at: '', updated_at: '', ...rest,
})

const offsetOf = (path: string) => new URL(path, 'http://localhost').searchParams.get('offset') ?? '0'

// One source the queue never promoted, so the MISSED panel has something to offer, and one
// that item 'a' already came from, which the panel must leave out.
const missedSource: Source = {
  id: 's1', kind: 'outlook_email', external_id: 'outlook_email:z', subject: 'Missed source',
  url: null, excerpt: null, observed_at: '',
}
const promotedSource: Source = {
  id: 's0', kind: 'outlook_email', external_id: 'outlook_email:a', subject: 'Already in the queue',
  url: null, excerpt: null, observed_at: '',
}
const promotedItem = item('p', 'Promoted item', { source_external_id: missedSource.external_id })

// Serves three work items over pages of two, so a page boundary is reachable, and answers
// every other endpoint the app touches during boot (health, session, sources, dismiss, promote).
const pagedQueue = (fetchMock: ReturnType<typeof vi.fn>) => {
  const firstPage = [item('a', 'First item'), item('b', 'Second item')]
  const secondPage = [item('c', 'Third item')]
  fetchMock.mockImplementation(async (path: string) => {
    const url = new URL(path, 'http://localhost')
    if (url.pathname === '/api/work-items') {
      const page = offsetOf(path) === '0' ? firstPage : secondPage
      return { ok: true, status: 200, json: async () => ({ items: page, total: 3, limit: 2, offset: Number(offsetOf(path)) }) }
    }
    if (url.pathname === '/api/sources') {
      return { ok: true, status: 200, json: async () => ({ items: [promotedSource, missedSource], total: 2, limit: 200, offset: 0 }) }
    }
    if (url.pathname.endsWith('/promote')) return { ok: true, status: 200, json: async () => promotedItem }
    if (url.pathname === '/api/session') return { ok: true, status: 200, json: async () => ({ csrf_token: 'csrf-test' }) }
    if (url.pathname.endsWith('/dismiss')) {
      const dismissedId = url.pathname.split('/')[3]
      const dismissed = [...firstPage, ...secondPage].find(i => i.id === dismissedId)
      return { ok: true, status: 200, json: async () => ({ ...dismissed, status: 'dismissed' }) }
    }
    return { ok: true, status: 200, json: async () => ({ status: 'ok', service: 'workboard' }) }
  })
  return { firstPage, secondPage }
}

// Five items over pages of two, so a third page sits behind the second and each Load more
// has to trust the envelope's `total` rather than the size of the page it just received.
const deepQueue = (fetchMock: ReturnType<typeof vi.fn>) => {
  const pages = [
    [item('a', 'First item'), item('b', 'Second item')],
    [item('c', 'Third item'), item('d', 'Fourth item')],
    [item('e', 'Fifth item')],
  ]
  fetchMock.mockImplementation(async (path: string) => {
    const url = new URL(path, 'http://localhost')
    if (url.pathname === '/api/work-items') {
      const page = pages[Number(offsetOf(path)) / 2] ?? []
      return { ok: true, status: 200, json: async () => ({ items: page, total: 5, limit: 2, offset: Number(offsetOf(path)) }) }
    }
    if (url.pathname === '/api/sources') return { ok: true, status: 200, json: async () => ({ items: [], total: 0, limit: 200, offset: 0 }) }
    if (url.pathname === '/api/session') return { ok: true, status: 200, json: async () => ({ csrf_token: 'csrf-test' }) }
    return { ok: true, status: 200, json: async () => ({ status: 'ok', service: 'workboard' }) }
  })
}

describe('Pagination', () => {
  it('pagination requests the next offset when Load more is clicked', async () => {
    const fetchMock = vi.fn()
    pagedQueue(fetchMock)
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    const queue = await screen.findByRole('region', { name: 'Work queue' })
    await within(queue).findByText('First item')
    fireEvent.click(await within(queue).findByRole('button', { name: 'Load more' }))
    await within(queue).findByText('Third item')

    const workItemCalls = fetchMock.mock.calls.filter(([path]) => new URL(String(path), 'http://localhost').pathname === '/api/work-items')
    expect(workItemCalls.map(([path]) => offsetOf(String(path)))).toContain('2')
  })

  it('pagination stops offering Load more once every item has loaded', async () => {
    const fetchMock = vi.fn()
    pagedQueue(fetchMock)
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    const queue = await screen.findByRole('region', { name: 'Work queue' })
    await within(queue).findByText('First item')
    fireEvent.click(await within(queue).findByRole('button', { name: 'Load more' }))
    await within(queue).findByText('Third item')

    expect(within(queue).queryByRole('button', { name: 'Load more' })).toBeNull()
  })

  it('pagination keeps paging past the second page while the envelope total exceeds what is loaded', async () => {
    const fetchMock = vi.fn()
    deepQueue(fetchMock)
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    const queue = await screen.findByRole('region', { name: 'Work queue' })
    await within(queue).findByText('First item')
    fireEvent.click(await within(queue).findByRole('button', { name: 'Load more' }))
    await within(queue).findByText('Third item')
    fireEvent.click(await within(queue).findByRole('button', { name: 'Load more' }))
    await within(queue).findByText('Fifth item')
  })

  it('pagination is not offered once the sample queue replaces the real one', async () => {
    const fetchMock = vi.fn()
    pagedQueue(fetchMock)
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    const queue = await screen.findByRole('region', { name: 'Work queue' })
    await within(queue).findByRole('button', { name: 'Load more' })
    fireEvent.click(screen.getByRole('button', { name: 'View sample' }))
    await within(queue).findByText(demoItems[0].title)

    expect(within(queue).queryByRole('button', { name: 'Load more' })).toBeNull()
  })
})

describe('Dismiss', () => {
  it('dismiss removes the item from the visible list', async () => {
    const fetchMock = vi.fn()
    const { firstPage } = pagedQueue(fetchMock)
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    const queue = await screen.findByRole('region', { name: 'Work queue' })
    await within(queue).findByText(firstPage[0].title)
    fireEvent.click(await screen.findByRole('button', { name: 'Dismiss' }))

    await within(queue).findByText(firstPage[1].title)
    expect(within(queue).queryByText(firstPage[0].title)).toBeNull()
  })

  it('dismiss sends the CSRF token header on its write request', async () => {
    const fetchMock = vi.fn()
    const { firstPage } = pagedQueue(fetchMock)
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    const queue = await screen.findByRole('region', { name: 'Work queue' })
    await within(queue).findByText(firstPage[0].title)
    fireEvent.click(await screen.findByRole('button', { name: 'Dismiss' }))
    await within(queue).findByText(firstPage[1].title)

    const dismissCall = fetchMock.mock.calls.find(([path]) => String(path).includes('/dismiss'))
    expect(dismissCall).toBeTruthy()
    const headers = dismissCall?.[1]?.headers as Record<string, string>
    expect(headers['X-CSRF-Token']).toBe('csrf-test')
  })

  // Dismissing is a status transition, not a delete, so the server's unfiltered total is
  // unchanged and the page still waiting behind it must stay reachable.
  it('dismiss leaves the unloaded page reachable behind Load more', async () => {
    const fetchMock = vi.fn()
    const { firstPage } = pagedQueue(fetchMock)
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    const queue = await screen.findByRole('region', { name: 'Work queue' })
    await within(queue).findByText(firstPage[0].title)
    fireEvent.click(await screen.findByRole('button', { name: 'Dismiss' }))
    await within(queue).findByText(firstPage[1].title)

    fireEvent.click(await within(queue).findByRole('button', { name: 'Load more' }))
    await within(queue).findByText('Third item')
  })
})

describe('Promote', () => {
  it('promote posts the missed source to its promote endpoint and shows the new item in the queue', async () => {
    const fetchMock = vi.fn()
    pagedQueue(fetchMock)
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    const panel = await screen.findByRole('group', { name: 'Missed sources' })
    fireEvent.click(within(panel).getByRole('button', { name: 'Promote' }))

    const queue = await screen.findByRole('region', { name: 'Work queue' })
    await within(queue).findByText(promotedItem.title)

    const promoteCall = fetchMock.mock.calls.find(([path]) => String(path).endsWith('/promote'))
    expect(promoteCall?.[0]).toBe(`/api/sources/${missedSource.id}/promote`)
    expect(promoteCall?.[1]?.method).toBe('POST')
    expect((promoteCall?.[1]?.headers as Record<string, string>)['X-CSRF-Token']).toBe('csrf-test')
  })

  it('promote only offers sources that are not already in the queue', async () => {
    const fetchMock = vi.fn()
    pagedQueue(fetchMock)
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    const panel = await screen.findByRole('group', { name: 'Missed sources' })
    await within(panel).findByText(missedSource.subject as string)
    expect(within(panel).queryByText(promotedSource.subject as string)).toBeNull()
  })
})
