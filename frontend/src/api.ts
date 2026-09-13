export type WorkStatus = 'pending' | 'in_progress' | 'blocked' | 'done'
export type SourceKind = 'outlook_email' | 'teams_message' | 'manual'

export interface WorkItem { id: string; title: string; summary: string | null; status: WorkStatus; source_kind: SourceKind; source_external_id: string | null; source_url: string | null; assigned_agent: string | null; due_at: string | null; created_at: string; updated_at: string; evidence?: Evidence[] }
export interface Evidence { id?: string; source_kind: SourceKind; external_id: string; excerpt: string | null; observed_at: string }
export interface Health { status: string; service: string }

export class ApiError extends Error { constructor(public status: number) { super(`Request failed (${status})`) } }
let csrfToken: string | null = null

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? 'GET').toUpperCase()
  const headers: Record<string, string> = { ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...(init?.headers as Record<string, string> | undefined) }
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && csrfToken) headers['X-CSRF-Token'] = csrfToken
  const response = await fetch(path, { ...init, headers, credentials: 'same-origin' })
  if (!response.ok) throw new ApiError(response.status)
  return response.status === 204 ? ({} as T) : response.json() as Promise<T>
}

export async function startLocalSession(localToken: string): Promise<void> {
  const response = await fetch('/api/session', { method: 'POST', credentials: 'same-origin', headers: { Authorization: `Bearer ${localToken}` } })
  if (!response.ok) throw new ApiError(response.status)
  csrfToken = (await response.json() as { csrf_token: string }).csrf_token
}

export async function restoreLocalSession(): Promise<void> {
  const response = await fetch('/api/session', { credentials: 'same-origin' })
  if (!response.ok) throw new ApiError(response.status)
  csrfToken = (await response.json() as { csrf_token: string }).csrf_token || null
}

export const beginMicrosoftConnect = async () => {
  const response = await request<{ authorization_url: string }>('/api/auth/microsoft/start')
  window.location.assign(response.authorization_url)
}
export const syncNow = () => request<{ created?: number; updated?: number; detail?: string }>('/api/sync', { method: 'POST' })
export const createDispatch = (id: string, client: 'codex' | 'claude-code', instruction: string) => request(`/api/work-items/${id}/dispatch`, { method: 'POST', body: JSON.stringify({ client, instruction }) })

export const getHealth = () => request<Health>('/api/health')
export const getWorkItems = () => request<WorkItem[]>('/api/work-items')
export const getWorkItem = (id: string) => request<WorkItem>(`/api/work-items/${id}`)
export const updateWorkItem = (id: string, update: Partial<Pick<WorkItem, 'status' | 'assigned_agent'>>) => request<WorkItem>(`/api/work-items/${id}`, { method: 'PATCH', body: JSON.stringify(update) })
