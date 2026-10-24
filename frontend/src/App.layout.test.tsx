import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import App from './App'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const offline = () => vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network unavailable')))
const responding = (status: number) => vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status }))

describe('Mail layout', () => {
  it('layout puts filters, queue and detail in three resizable panes', async () => {
    offline()

    render(<App />)

    expect(await screen.findByRole('region', { name: 'Filters' })).toBeTruthy()
    expect(screen.getByRole('region', { name: 'Work queue' })).toBeTruthy()
    expect(screen.getByRole('region', { name: 'Work item detail' })).toBeTruthy()
    expect(screen.getAllByRole('separator')).toHaveLength(2)
  })

  it('layout opens the command palette on Cmd+K and jumps to the chosen work item', async () => {
    offline()

    render(<App />)
    await screen.findByRole('region', { name: 'Work queue' })
    fireEvent.keyDown(window, { key: 'k', metaKey: true })

    const palette = await screen.findByRole('dialog', { name: 'Command palette' })
    fireEvent.change(within(palette).getByRole('combobox'), { target: { value: 'rollout' } })
    const option = await within(palette).findByRole('option', { name: /Confirm the rollout owner/ })
    fireEvent.click(option)

    const detail = screen.getByRole('region', { name: 'Work item detail' })
    await waitFor(() => expect(within(detail).getByRole('heading', { name: 'Confirm the rollout owner' })).toBeTruthy())
  })

  it('layout asks for the local token instead of demo data when the API answers 401', async () => {
    responding(401)

    render(<App />)

    expect(await screen.findByLabelText('Local API token')).toBeTruthy()
    expect(screen.queryByText('Send the revised project estimate')).toBeNull()
  })

  it('layout records an agent handoff without offering a shell command', async () => {
    offline()

    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: 'Use Codex' }))

    expect(await screen.findByText('Sample item. Nothing will be dispatched.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Copy command' })).toBeNull()
  })

  it('layout says a handoff is only recorded, since no agent picks it up yet', async () => {
    offline()

    render(<App />)
    await screen.findByRole('button', { name: 'Use Codex' })

    expect(screen.getByText('Magic Tower only records the request. Nothing picks it up yet.')).toBeTruthy()
    expect(screen.queryByText(/local agent client/)).toBeNull()
  })

  it('layout confirms a live handoff as recorded, not queued for an agent', async () => {
    const item = { id: 'item-1', title: 'Check the export', summary: null, status: 'pending', priority: 'medium', source_kind: 'manual',
      source_external_id: null, source_url: null, created_at: '2026-10-24T10:00:00Z', updated_at: '2026-10-24T10:00:00Z', evidence: [] }
    vi.stubGlobal('fetch', vi.fn(async (path: string) => ({
      ok: true,
      status: 200,
      json: async () => path === '/api/work-items' ? { items: [item], total: 1, limit: 50, offset: 0 }
        : path === '/api/work-items/item-1' ? item
        : path === '/api/session' ? { csrf_token: 'csrf-test' }
        : path.startsWith('/api/sources') ? { items: [], total: 0, limit: 200, offset: 0 }
        : path.endsWith('/dispatch') ? { id: 'dispatch-1' }
        : { status: 'ok', service: 'workboard' },
    })))

    render(<App />)
    fireEvent.click((await screen.findAllByText('Check the export'))[0])
    fireEvent.click(await screen.findByRole('button', { name: 'Use Codex' }))

    expect(await screen.findByText('Recorded a codex handoff request. Nothing acts on it yet.')).toBeTruthy()
  })
})
