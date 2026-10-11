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

// Renders from a real (mocked) API body, so these tests also cover api.ts's
// `page.items` unwrap rather than the offline demo fallback.
const queue = (items: WorkItem[]) => vi.stubGlobal('fetch', vi.fn(async (path: string) => ({
  ok: true,
  status: 200,
  json: async () => path === '/api/work-items' ? { items } : path === '/api/session' ? { csrf_token: 'csrf-test' } : { status: 'ok', service: 'workboard' },
})))

describe('Triage view', () => {
  it('triage groups items by source kind and thread', async () => {
    queue([
      item('a', 'Q3 budget review', 'outlook_email'),
      item('b', 'Re: Q3 budget review', 'outlook_email'),
      item('c', 'Q3 budget review', 'manual'),
    ])

    render(<App />)

    const outlook = await screen.findByRole('group', { name: 'Outlook · Q3 budget review' })
    expect(within(outlook).getByText('Q3 budget review')).toBeTruthy()
    expect(within(outlook).getByText('Re: Q3 budget review')).toBeTruthy()

    const manual = screen.getByRole('group', { name: 'Manual · Q3 budget review' })
    expect(within(manual).getByText('Q3 budget review')).toBeTruthy()
    expect(within(manual).queryByText('Re: Q3 budget review')).toBeNull()
  })

  it('triage keeps different threads of one source kind apart', async () => {
    queue([
      item('a', 'Q3 budget review', 'outlook_email'),
      item('b', 'Standup notes', 'outlook_email'),
      item('c', 'Re: Standup notes', 'outlook_email'),
    ])

    render(<App />)

    const budget = await screen.findByRole('group', { name: 'Outlook · Q3 budget review' })
    expect(within(budget).queryByText('Standup notes')).toBeNull()
    expect(within(budget).queryByText('Re: Standup notes')).toBeNull()

    const standup = screen.getByRole('group', { name: 'Outlook · Standup notes' })
    expect(within(standup).getByText('Standup notes')).toBeTruthy()
    expect(within(standup).getByText('Re: Standup notes')).toBeTruthy()
    expect(within(standup).queryByText('Q3 budget review')).toBeNull()
  })

  it('triage labels a thread with no subject left after the reply markers', async () => {
    queue([item('a', 'Re:', 'outlook_email'), item('b', 'Fwd: ', 'outlook_email')])

    render(<App />)

    const group = await screen.findByRole('group', { name: 'Outlook · (no subject)' })
    expect(within(group).getByLabelText('2 items')).toBeTruthy()
  })

  it('triage group counts match the data', async () => {
    queue([
      item('a', 'Launch checklist', 'outlook_email'),
      item('b', 'RE: Launch checklist', 'outlook_email'),
      item('c', 'Fwd: Launch checklist', 'outlook_email'),
      item('d', 'Standup notes', 'manual'),
    ])

    render(<App />)

    const outlook = await screen.findByRole('group', { name: 'Outlook · Launch checklist' })
    expect(within(outlook).getByLabelText('3 items')).toBeTruthy()

    const manual = screen.getByRole('group', { name: 'Manual · Standup notes' })
    expect(within(manual).getByLabelText('1 item')).toBeTruthy()
  })

  it('triage says the queue is empty instead of rendering blank', async () => {
    queue([])

    render(<App />)

    const list = await screen.findByRole('region', { name: 'Work queue' })
    expect(within(list).getByText('Nothing to triage yet.')).toBeTruthy()
    expect(within(list).queryAllByRole('group')).toHaveLength(0)
  })

  it('triage separates an empty queue from filters that hide every item', async () => {
    queue([item('a', 'Q3 budget review', 'outlook_email')])

    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: /^Done/ }))

    const list = screen.getByRole('region', { name: 'Work queue' })
    expect(within(list).getByText('No tasks match these filters.')).toBeTruthy()
    expect(within(list).queryByText('Nothing to triage yet.')).toBeNull()
  })
})
