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

describe('Freshservice work items', () => {
  it('the Freshservice source filter shows only Freshservice items', async () => {
    queue([
      item('a', 'Reset the shared printer', 'freshservice', { source_url: 'https://example.freshservice.com/a/tickets/1001' }),
      item('b', 'Send the revised estimate', 'outlook_email'),
    ])

    render(<App />)
    const list = await screen.findByRole('region', { name: 'Work queue' })
    await within(list).findByText('Reset the shared printer')
    fireEvent.click(await screen.findByRole('button', { name: /Freshservice/ }))

    expect(within(list).getByText('Reset the shared printer')).toBeTruthy()
    expect(within(list).queryByText('Send the revised estimate')).toBeNull()
  })
})
