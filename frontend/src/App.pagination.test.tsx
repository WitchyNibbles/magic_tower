import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import App from './App'
import type { WorkItem } from './api'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const item = (id: string, title: string, rest: Partial<WorkItem> = {}): WorkItem => ({
  id, title, summary: null, status: 'pending', source_kind: 'outlook_email', source_external_id: `outlook_email:${id}`,
  source_url: null, assigned_agent: null, due_at: null, created_at: '', updated_at: '', ...rest,
})

const offsetOf = (path: string) => new URL(path, 'http://localhost').searchParams.get('offset') ?? '0'

// Serves three work items over pages of two, so a page boundary is reachable, and answers
// every other endpoint the app touches during boot (health check, session, dismiss/promote).
const pagedQueue = (fetchMock: ReturnType<typeof vi.fn>) => {
  const firstPage = [item('a', 'First item'), item('b', 'Second item')]
  const secondPage = [item('c', 'Third item')]
  fetchMock.mockImplementation(async (path: string) => {
    const url = new URL(path, 'http://localhost')
    if (url.pathname === '/api/work-items') {
      const page = offsetOf(path) === '0' ? firstPage : secondPage
      return { ok: true, status: 200, json: async () => ({ items: page, total: 3, limit: 2, offset: Number(offsetOf(path)) }) }
    }
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
})
