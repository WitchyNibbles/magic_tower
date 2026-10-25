import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import App from './App'
import type { Analysis, WorkItem } from './api'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const hoursAgo = (hours: number) => new Date(Date.now() - hours * 3_600_000).toISOString()

const analysis = (rest: Partial<Analysis> = {}): Analysis => ({
  summary: 'Renew the invented gateway certificate before it lapses.',
  details: { asked: 'Renew the certificate for the demo gateway.', systems: [], known: '', next_step: '', open_questions: [] },
  analyzed_at: hoursAgo(2), analyzer: 'grimoire', stale: false, ...rest,
})

const item = (rest: Partial<WorkItem> = {}): WorkItem => ({
  id: 'a', title: 'Rotate the invented certificate', summary: null, status: 'pending', source_kind: 'jira', source_external_id: 'jira:1',
  source_url: null, assigned_agent: null, due_at: null, created_at: '', updated_at: '',
  evidence: [{ source_kind: 'jira', external_id: 'jira:1', excerpt: 'The demo host cert expires soon.', observed_at: '' }], analysis: null, ...rest,
})

const queue = (items: WorkItem[]) => vi.stubGlobal('fetch', vi.fn(async (path: string) => ({
  ok: true,
  status: 200,
  json: async () => path === '/api/work-items' ? { items } : path.startsWith('/api/work-items/') ? items.find(i => path.endsWith(`/${i.id}`)) : path === '/api/session' ? { csrf_token: 'csrf-test' } : { status: 'ok', service: 'workboard' },
})))

const openDetail = async () => {
  const list = await screen.findByRole('region', { name: 'Work queue' })
  fireEvent.click((await within(list).findByText('Rotate the invented certificate')).closest('button')!)
  await screen.findByRole('heading', { level: 2, name: 'Rotate the invented certificate' })
  return { list, detail: screen.getByRole('region', { name: 'Work item detail' }) }
}

describe('Grimoire analysis', () => {
  it('analysis summary leads the list row and the detail pane', async () => {
    queue([item({ summary: 'Typed by hand.', analysis: analysis() })])

    render(<App />)
    const { list, detail } = await openDetail()

    expect(within(list).getByText('Renew the invented gateway certificate before it lapses.')).toBeTruthy()
    expect(within(list).queryByText('Typed by hand.')).toBeNull()
    expect(within(detail).getByText('Renew the invented gateway certificate before it lapses.')).toBeTruthy()
    expect(within(detail).getByText(/Analysed 2 hours ago by grimoire/)).toBeTruthy()
    expect(within(detail).getByText('The demo host cert expires soon.')).toBeTruthy()
    expect(within(detail).queryByText('No analysis yet.')).toBeNull()
  })

  it('details sections render only when present', async () => {
    queue([item({ analysis: analysis({ details: {
      asked: 'Renew the certificate for the demo gateway.', systems: ['demo-gateway', 'demo-proxy'], known: '', next_step: 'Request a new certificate.', open_questions: ['Who owns the demo gateway?'],
    } }) })])

    render(<App />)
    const { detail } = await openDetail()

    for (const heading of ['Asked', 'Systems', 'Next step', 'Open questions']) expect(within(detail).getByRole('heading', { level: 3, name: heading })).toBeTruthy()
    expect(within(detail).queryByRole('heading', { name: "What's known" })).toBeNull()
    expect(within(detail).getByText('Renew the certificate for the demo gateway.')).toBeTruthy()
    expect(within(detail).getByText('demo-gateway')).toBeTruthy()
    expect(within(detail).getByText('demo-proxy')).toBeTruthy()
    expect(within(detail).getByText('Request a new certificate.')).toBeTruthy()
    expect(within(detail).getByText('Who owns the demo gateway?')).toBeTruthy()
  })

  it('known facts show under "What\'s known"', async () => {
    queue([item({ analysis: analysis({ details: { asked: 'Renew it.', systems: [], known: 'The old one expires on Friday.', next_step: '', open_questions: [] } }) })])

    render(<App />)
    const { detail } = await openDetail()

    expect(within(detail).getByRole('heading', { level: 3, name: "What's known" })).toBeTruthy()
    expect(within(detail).getByText('The old one expires on Friday.')).toBeTruthy()
  })

  it('stale analysis shows the hint', async () => {
    queue([item({ analysis: analysis({ stale: true }) })])

    render(<App />)
    const { detail } = await openDetail()

    expect(within(detail).getByText('The source changed since this was analysed.')).toBeTruthy()
  })

  it('a current analysis shows no stale hint', async () => {
    queue([item({ analysis: analysis() })])

    render(<App />)
    const { detail } = await openDetail()

    expect(within(detail).queryByText('The source changed since this was analysed.')).toBeNull()
  })

  it('markup in an analysis renders as literal text', async () => {
    const markup = '<img src=x onerror=alert(1)>'
    queue([item({ analysis: analysis({ summary: markup, details: { asked: markup, systems: [markup], known: markup, next_step: markup, open_questions: [markup] } }) })])

    render(<App />)
    const { detail } = await openDetail()

    expect(within(detail).getAllByText(markup).length).toBeGreaterThan(0)
    expect(document.querySelector('img[src="x"]')).toBeNull()
    expect(document.querySelectorAll('img[onerror]')).toHaveLength(0)
  })

  it('no analysis falls back to source text and says so', async () => {
    queue([item()])

    render(<App />)
    const { list, detail } = await openDetail()

    expect(within(list).getByText('The demo host cert expires soon.')).toBeTruthy()
    expect(within(detail).getAllByText('The demo host cert expires soon.').length).toBeGreaterThan(0)
    expect(within(detail).getByText('No analysis yet.')).toBeTruthy()
  })

  it('no Codex or Claude Code buttons remain', async () => {
    queue([item({ analysis: analysis() })])

    render(<App />)
    await openDetail()

    expect(screen.queryByRole('button', { name: /Codex/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /Claude Code/ })).toBeNull()
  })
})
