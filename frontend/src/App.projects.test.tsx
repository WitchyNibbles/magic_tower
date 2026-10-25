import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import App from './App'
import type { ProjectSnapshot } from './api'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const snapshot = (rest: Partial<ProjectSnapshot> = {}): ProjectSnapshot => ({
  updated_at: new Date(Date.now() - 3_600_000).toISOString(),
  projects: [
    {
      code: 'PRJ-A', name: 'Invented widget project', status: 'active', open_questions: 2, pending_prod_steps: ['Run the widget migration'],
      tasks: [
        { title: 'Draft the widget plan', status: 'in_progress', pr_url: 'https://example.test/pull/7' },
        { title: 'Review the notes', status: 'todo', pr_url: null },
      ],
    },
    { code: 'PRJ-B', name: 'Invented archive project', status: 'done', open_questions: 0, pending_prod_steps: [], tasks: [] },
  ],
  ...rest,
})

const respond = (projects: ProjectSnapshot) => vi.stubGlobal('fetch', vi.fn(async (path: string) => ({
  ok: true,
  status: 200,
  json: async () => path === '/api/work-items' ? { items: [] }
    : path === '/api/projects' ? projects
      : path === '/api/session' ? { csrf_token: 'csrf-test' }
        : path.startsWith('/api/sources') ? { items: [] } : { status: 'ok', service: 'workboard' },
})))

const openProjects = async () => {
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: 'Projects' }))
  return screen.findByRole('region', { name: 'Projects' })
}

describe('Projects view', () => {
  it('projects view lists codes, statuses, counts and PR links', async () => {
    respond(snapshot())

    const view = await openProjects()

    expect(within(view).getByText('PRJ-A')).toBeTruthy()
    expect(within(view).getByText('Invented widget project')).toBeTruthy()
    expect(within(view).getByText('Active')).toBeTruthy()
    expect(within(view).getByText('Done')).toBeTruthy()
    expect(within(view).getByText('Draft the widget plan')).toBeTruthy()
    expect(within(view).getByText('In progress')).toBeTruthy()
    expect(within(view).getByText('To do')).toBeTruthy()
    expect(within(view).getByText('2 open questions')).toBeTruthy()
    expect(within(view).getByText('Run the widget migration')).toBeTruthy()
    const link = within(view).getByRole('link', { name: 'Pull request' })
    expect(link.getAttribute('href')).toBe('https://example.test/pull/7')
    expect(within(view).getByText(/Updated 1 hour ago/)).toBeTruthy()
  })

  it('projects view empty state reads "No projects from grimoire yet."', async () => {
    respond({ projects: [], updated_at: null })

    const view = await openProjects()

    expect(within(view).getByText('No projects from grimoire yet.')).toBeTruthy()
  })

  it('projects view hides the work filters, which do not apply to it', async () => {
    respond(snapshot())

    await openProjects()

    expect(screen.queryByRole('navigation', { name: 'Work status' })).toBeNull()
    expect(screen.queryByText('SOURCES')).toBeNull()
    expect(screen.getByRole('button', { name: 'Sync now' })).toBeTruthy()
  })

  it('projects view leads back to the work queue', async () => {
    respond(snapshot())

    await openProjects()
    fireEvent.click(screen.getByRole('button', { name: 'Work' }))

    expect(await screen.findByRole('region', { name: 'Work queue' })).toBeTruthy()
    expect(screen.queryByRole('region', { name: 'Projects' })).toBeNull()
  })
})
