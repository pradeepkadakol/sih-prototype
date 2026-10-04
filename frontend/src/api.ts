const root = import.meta.env.VITE_API_URL || ''

export async function api<T>(path: string, token: string | null, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(`${root}/api${path}`, {
    method,
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  let data: unknown
  try { data = await response.json() } catch { throw new Error(`Server returned ${response.status} without JSON`) }
  if (!response.ok) {
    const detail = typeof data === 'object' && data && 'detail' in data ? (data as { detail: unknown }).detail : 'Request failed'
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return data as T
}

export function niceDate(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '—'
}

export function title(value: string) { return value.replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase()) }
