import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import App from './App'
import type { SourceKind, WorkItem } from './api'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const item = (id: string, title: string, source_kind: SourceKind, rest: Partial<WorkItem> = {}): WorkItem => ({
  id, title, summary: null, status: 'pending', source_kind, source_external_id: `${source_kind}:${id}`,
  source_url: null, assigned_agent: null, due_at: null, created_at: '', updated_at: '', ...rest,
})

const queue = (items: WorkItem[]) => vi.stubGlobal('fetch', vi.fn(async (path: string) => ({
  ok: true,
  status: 200,
  json: async () => path === '/api/work-items' ? { items } : path === '/api/session' ? { csrf_token: 'csrf-test' } : { status: 'ok', service: 'workboard' },
})))

describe('Jira work items', () => {
  it('jira items show their issue key linked back to the browse URL', async () => {
    queue([
      item('a', 'Fix the login redirect', 'jira', { source_url: 'https://example.atlassian.net/browse/OPS-42' }),
    ])

    render(<App />)

    const link = await screen.findByRole('link', { name: 'OPS-42' })
    expect(link.getAttribute('href')).toBe('https://example.atlassian.net/browse/OPS-42')
  })

  it('the jira source filter shows only jira items', async () => {
    queue([
      item('a', 'Fix the login redirect', 'jira', { source_url: 'https://example.atlassian.net/browse/OPS-42' }),
      item('b', 'Send the revised estimate', 'outlook_email'),
    ])

    render(<App />)
    const list = await screen.findByRole('region', { name: 'Work queue' })
    await within(list).findByText('Fix the login redirect')
    fireEvent.click(await screen.findByRole('button', { name: /Jira/ }))

    expect(within(list).getByText('Fix the login redirect')).toBeTruthy()
    expect(within(list).queryByText('Send the revised estimate')).toBeNull()
  })
})
