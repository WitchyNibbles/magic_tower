import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import App from './App'
import type { Evidence, SourceKind, WorkItem } from './api'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const evidence = (excerpt: string | null, source_kind: SourceKind = 'jira'): Evidence => ({
  source_kind, external_id: 'jira:1', excerpt, observed_at: '',
})

const item = (id: string, title: string, rest: Partial<WorkItem> = {}): WorkItem => ({
  id, title, summary: null, status: 'pending', source_kind: 'jira', source_external_id: `jira:${id}`,
  source_url: null, assigned_agent: null, due_at: null, created_at: '', updated_at: '', evidence: [], ...rest,
})

const queue = (items: WorkItem[]) => vi.stubGlobal('fetch', vi.fn(async (path: string) => ({
  ok: true,
  status: 200,
  json: async () => path === '/api/work-items' ? { items } : path.startsWith('/api/work-items/') ? items.find(i => path.endsWith(`/${i.id}`)) : path === '/api/session' ? { csrf_token: 'csrf-test' } : { status: 'ok', service: 'workboard' },
})))

const openRow = async (title: string) => {
  const list = await screen.findByRole('region', { name: 'Work queue' })
  fireEvent.click((await within(list).findByText(title)).closest('button')!)
  return list
}

describe('Work item summaries', () => {
  it('the list row shows the summary when the item has one', async () => {
    queue([item('a', 'Rotate the invented certificate', { summary: 'Written by hand.', evidence: [evidence('Source text.')] })])

    render(<App />)

    const list = await screen.findByRole('region', { name: 'Work queue' })
    expect(await within(list).findByText('Written by hand.')).toBeTruthy()
    expect(within(list).queryByText('Source text.')).toBeNull()
  })

  it('the list row falls back to the first evidence excerpt that has text', async () => {
    queue([item('a', 'Rotate the invented certificate', { evidence: [evidence(null), evidence('   '), evidence('The demo host cert expires soon.')] })])

    render(<App />)

    const list = await screen.findByRole('region', { name: 'Work queue' })
    expect(await within(list).findByText('The demo host cert expires soon.')).toBeTruthy()
    expect(within(list).queryByText('No summary yet')).toBeNull()
  })

  it('the list row keeps its empty text when there is neither a summary nor an excerpt', async () => {
    queue([item('a', 'Rotate the invented certificate', { evidence: [evidence(null)] })])

    render(<App />)

    const list = await screen.findByRole('region', { name: 'Work queue' })
    expect(await within(list).findByText('No summary yet')).toBeTruthy()
  })

  it('the detail pane shows the excerpt as the summary when the item has none', async () => {
    queue([item('a', 'Rotate the invented certificate', { evidence: [evidence('The demo host cert expires soon.')] })])

    render(<App />)
    await openRow('Rotate the invented certificate')

    const heading = await screen.findByRole('heading', { level: 2, name: 'Rotate the invented certificate' })
    expect(within(heading.parentElement!).getByText('The demo host cert expires soon.')).toBeTruthy()
    expect(within(heading.parentElement!).queryByText('No summary was added to this task.')).toBeNull()
  })

  it('the detail pane renders no blockquote for an evidence row without an excerpt', async () => {
    queue([item('a', 'Rotate the invented certificate', { evidence: [evidence(null), evidence('The demo host cert expires soon.')] })])

    render(<App />)
    await openRow('Rotate the invented certificate')

    await screen.findByRole('heading', { level: 2, name: 'Rotate the invented certificate' })
    const quotes = document.querySelectorAll('blockquote')
    expect(quotes).toHaveLength(1)
    expect(quotes[0].textContent).toContain('The demo host cert expires soon.')
  })

  it('search matches the excerpt of an item that has no summary', async () => {
    queue([
      item('a', 'Rotate the invented certificate', { evidence: [evidence('Mentions the zebra-gateway host.')] }),
      item('b', 'Send the revised estimate', { evidence: [evidence('Nothing relevant.')] }),
    ])

    render(<App />)
    const list = await screen.findByRole('region', { name: 'Work queue' })
    await within(list).findByText('Send the revised estimate')
    fireEvent.change(screen.getByLabelText('Search tasks'), { target: { value: 'zebra-gateway' } })

    expect(within(list).getByText('Rotate the invented certificate')).toBeTruthy()
    expect(within(list).queryByText('Send the revised estimate')).toBeNull()
  })
})
