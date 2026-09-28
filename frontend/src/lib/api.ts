import { supabase } from './supabase'

const API_BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/$/, '')

/** Local dev uses the Vite `/api` proxy. Production calls the Cloud Run API directly. */
export function apiUrl(path: string): string {
  if (!API_BASE) return path
  const stripped = path.replace(/^\/api(?=\/|$)/, '')
  return `${API_BASE}${stripped.startsWith('/') ? stripped : `/${stripped}`}`
}

export async function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers)
  if (supabase) {
    const { data } = await supabase.auth.getSession()
    const token = data.session?.access_token
    if (token) headers.set('Authorization', `Bearer ${token}`)
  }
  return fetch(apiUrl(input), { ...init, headers })
}
