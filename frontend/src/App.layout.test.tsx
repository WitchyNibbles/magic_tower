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

  it('layout still copies the bounded dispatch command to the clipboard', async () => {
    offline()
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })

    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: 'Use Codex' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Copy command' }))

    await waitFor(() => expect(writeText).toHaveBeenCalledWith('scripts/pending-work context demo-email'))
  })
})
