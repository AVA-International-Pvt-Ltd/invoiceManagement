import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import type { Session } from '@supabase/supabase-js'
import { ALLOWED_EMAIL_DOMAIN, isAllowedOrgEmail, supabase, supabaseConfigured } from './lib/supabase'

type AuthContextValue = {
  email: string
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue>({
  email: '',
  signOut: async () => {},
})

export function useAuth(): AuthContextValue {
  return useContext(AuthContext)
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 0 1-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.875 2.684-6.615z"
      />
      <path
        fill="#34A853"
        d="M9 18c2.43 0 4.467-.806 5.956-2.184l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z"
      />
      <path
        fill="#FBBC05"
        d="M3.964 10.706A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.706V4.962H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.038l3.007-2.332z"
      />
      <path
        fill="#EA4335"
        d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.962L3.964 7.294C4.672 5.163 6.656 3.58 9 3.58z"
      />
    </svg>
  )
}

function BrandLockup() {
  return (
    <div className="brand login-brand">
      <span className="brand-mark">FI</span>
      <div>
        <p className="brand-title">FinIntel</p>
        <p className="brand-sub">Document intelligence</p>
      </div>
    </div>
  )
}

function LoginFrame({ children }: { children: ReactNode }) {
  return (
    <div className="login-screen">
      <aside className="login-hero">
        <BrandLockup />
        <div className="login-hero-copy">
          <p className="eyebrow eyebrow-light">AVAIPL workspace</p>
          <h1>Financial documents, ready for the books.</h1>
          <ul className="login-points">
            <li>Ingest invoices, credit notes, and R4C files</li>
            <li>Review extraction quality before anything is exported</li>
            <li>Search by invoice number, vendor, and GSTIN</li>
          </ul>
        </div>
        <p className="login-footnote">Access is limited to @{ALLOWED_EMAIL_DOMAIN} Google accounts.</p>
      </aside>
      <section className="login-panel">{children}</section>
    </div>
  )
}

function LoginScreen({
  error,
  busy,
  onSignIn,
}: {
  error: string
  busy: boolean
  onSignIn: () => void
}) {
  return (
    <LoginFrame>
      <section className="login-card">
        <h2>Sign in</h2>
        <p className="login-copy">
          Continue with your organisation Google account. Personal Gmail addresses are turned away.
        </p>
        {error ? <p className="login-error">{error}</p> : null}
        <button type="button" className="google-btn" onClick={onSignIn} disabled={busy || !supabase}>
          <GoogleIcon />
          {busy ? 'Redirecting to Google…' : 'Continue with Google'}
        </button>
        <p className="login-fine">Only @{ALLOWED_EMAIL_DOMAIN}</p>
      </section>
    </LoginFrame>
  )
}

function SetupScreen() {
  return (
    <LoginFrame>
      <section className="login-card">
        <h2>Connect the workspace</h2>
        <p className="login-copy">
          Add <code>VITE_SUPABASE_URL</code> and <code>VITE_SUPABASE_ANON_KEY</code> to{' '}
          <code>frontend/.env.local</code>, then restart the app.
        </p>
      </section>
    </LoginFrame>
  )
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(supabaseConfigured)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [email, setEmail] = useState('')

  useEffect(() => {
    const client = supabase
    if (!client) return

    const applySession = async (next: Session | null) => {
      const nextEmail = next?.user.email ?? ''
      if (next && !isAllowedOrgEmail(nextEmail)) {
        await client.auth.signOut()
        setSession(null)
        setEmail('')
        setError(`Only @${ALLOWED_EMAIL_DOMAIN} Google accounts can sign in.`)
        setLoading(false)
        return
      }
      setSession(next)
      setEmail(nextEmail)
      if (next) setError('')
      setLoading(false)
    }

    client.auth.getSession().then(({ data }) => {
      void applySession(data.session)
    })

    const { data } = client.auth.onAuthStateChange((_event, next) => {
      void applySession(next)
    })

    return () => data.subscription.unsubscribe()
  }, [])

  const signIn = async () => {
    if (!supabase) return
    setBusy(true)
    setError('')
    const { error: signInError } = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: {
        redirectTo: window.location.origin,
        queryParams: {
          hd: ALLOWED_EMAIL_DOMAIN,
          prompt: 'select_account',
        },
      },
    })
    if (signInError) {
      setError(signInError.message)
      setBusy(false)
    }
  }

  const signOut = async () => {
    if (!supabase) return
    await supabase.auth.signOut()
    setSession(null)
    setEmail('')
  }

  if (!supabaseConfigured) return <SetupScreen />
  if (loading) {
    return (
      <LoginFrame>
        <section className="login-card">
          <h2>FinIntel</h2>
          <p className="login-copy">Checking your session…</p>
        </section>
      </LoginFrame>
    )
  }
  if (!session) return <LoginScreen error={error} busy={busy} onSignIn={() => void signIn()} />

  return <AuthContext.Provider value={{ email, signOut }}>{children}</AuthContext.Provider>
}
