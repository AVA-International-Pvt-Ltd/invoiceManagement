import { createClient, type SupabaseClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL?.trim() ?? ''
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY?.trim() ?? ''

export const ALLOWED_EMAIL_DOMAIN = (
  import.meta.env.VITE_ALLOWED_EMAIL_DOMAIN || 'avaipl.com'
)
  .trim()
  .toLowerCase()

export const supabaseConfigured = Boolean(url && anonKey)

export const supabase: SupabaseClient | null = supabaseConfigured
  ? createClient(url, anonKey, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
    })
  : null

export function isAllowedOrgEmail(email: string | null | undefined): boolean {
  if (!email) return false
  return email.trim().toLowerCase().endsWith(`@${ALLOWED_EMAIL_DOMAIN}`)
}
