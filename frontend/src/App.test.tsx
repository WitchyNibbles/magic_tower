import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import App from './App'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('App', () => {
  it('falls back to the sample queue when the API is unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network unavailable')))

    render(<App />)

    expect(await screen.findAllByText('Send the revised project estimate')).toHaveLength(2)
    expect(screen.getByText('API offline')).toBeTruthy()
  })

  it('a locked API reads as locked, not offline', async () => {
    vi.stubGlobal('fetch', vi.fn(async (path: string) => path === '/api/health'
      ? { ok: true, status: 200, json: async () => ({ status: 'ok', service: 'workboard' }) }
      : { ok: false, status: 401, json: async () => ({ detail: 'local API token required' }) }))

    render(<App />)

    expect(await screen.findByText('Unlock Magic Tower')).toBeTruthy()
    expect(screen.getByText('Locked')).toBeTruthy()
    expect(screen.queryByText('API offline')).toBeNull()
  })

  it('an empty connected queue says so and offers the sample items', async () => {
    vi.stubGlobal('fetch', vi.fn(async (path: string) => ({
      ok: true,
      status: 200,
      json: async () => path === '/api/work-items' ? { items: [], total: 0, limit: 50, offset: 0 }
        : path === '/api/session' ? { csrf_token: 'csrf-test' }
        : path.startsWith('/api/sources') ? { items: [], total: 0, limit: 200, offset: 0 }
        : { status: 'ok', service: 'workboard' },
    })))

    render(<App />)

    expect(await screen.findByText('API connected')).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'No work items' })).toBeTruthy()
    expect(screen.getByText('Set up Jira or connect Outlook, then press Sync now. Or load the sample items.')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Load sample items' }))
    expect(await screen.findAllByText('Send the revised project estimate')).toHaveLength(2)
    expect(await screen.findByText('Showing sample items, not your queue.')).toBeTruthy()
  })
})
