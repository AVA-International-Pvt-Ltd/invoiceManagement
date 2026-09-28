import { useEffect, useState } from 'react'
import { useAuth } from './auth'
import { apiUrl } from './lib/api'
import { Dashboard } from './pages/Dashboard'
import { Documents } from './pages/Documents'
import { Issues } from './pages/Issues'
import { Search } from './pages/Search'
import { Upload } from './pages/Upload'
import { DuplicatesPanel, TopAlerts } from './components/TopAlerts'
import './App.css'

type Page = 'dashboard' | 'documents' | 'upload' | 'search' | 'issues'
type IssuesTab = 'problems' | 'duplicates'
type HealthResponse = { status: string }

const NAV: { id: Page; label: string }[] = [
  { id: 'dashboard', label: 'Overview' },
  { id: 'documents', label: 'Documents' },
  { id: 'upload', label: 'Upload' },
  { id: 'issues', label: 'Quality' },
  { id: 'search', label: 'Search' },
]

const PAGE_TITLES: Record<Page, { title: string; subtitle: string }> = {
  dashboard: {
    title: 'Overview',
    subtitle: 'Workspace health, value, and what needs a decision',
  },
  documents: {
    title: 'Documents',
    subtitle: 'Review extracted invoices, credit notes, and settlements',
  },
  upload: {
    title: 'Upload',
    subtitle: 'Add PDFs and images. Extraction starts as soon as they land',
  },
  issues: {
    title: 'Quality',
    subtitle: 'Fix failed extractions and resolve duplicate uploads',
  },
  search: {
    title: 'Search',
    subtitle: 'Find a document by invoice number, vendor, or GSTIN',
  },
}

function initials(email: string) {
  const local = email.split('@')[0] ?? ''
  const parts = local.split(/[._-]/).filter(Boolean)
  if (parts.length >= 2) return `${parts[0][0] ?? ''}${parts[1][0] ?? ''}`.toUpperCase()
  return local.slice(0, 2).toUpperCase()
}

function NavIcon({ id }: { id: Page }) {
  const props = {
    width: 18,
    height: 18,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.75,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
  }
  if (id === 'dashboard') {
    return (
      <svg {...props}>
        <rect x="3" y="3" width="7" height="7" rx="1.5" />
        <rect x="14" y="3" width="7" height="7" rx="1.5" />
        <rect x="3" y="14" width="7" height="7" rx="1.5" />
        <rect x="14" y="14" width="7" height="7" rx="1.5" />
      </svg>
    )
  }
  if (id === 'documents') {
    return (
      <svg {...props}>
        <path d="M7 3.5h7l5 5V20a1.5 1.5 0 0 1-1.5 1.5h-10.5A1.5 1.5 0 0 1 5.5 20V5A1.5 1.5 0 0 1 7 3.5z" />
        <path d="M14 3.5V9h5.5" />
        <path d="M8.5 13h7M8.5 16.5h5" />
      </svg>
    )
  }
  if (id === 'upload') {
    return (
      <svg {...props}>
        <path d="M12 16V5" />
        <path d="M8 8.5 12 4.5 16 8.5" />
        <path d="M5 19.5h14" />
      </svg>
    )
  }
  if (id === 'issues') {
    return (
      <svg {...props}>
        <path d="M12 4.5 20 19H4L12 4.5z" />
        <path d="M12 10v4.5" />
        <path d="M12 16.8h.01" />
      </svg>
    )
  }
  return (
    <svg {...props}>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M16 16.5 20 20.5" />
    </svg>
  )
}

function App() {
  const [page, setPage] = useState<Page>('dashboard')
  const [issuesTab, setIssuesTab] = useState<IssuesTab>('problems')
  const [backendStatus, setBackendStatus] = useState<'loading' | 'ok' | 'error'>('loading')
  const [docRefreshKey, setDocRefreshKey] = useState(0)
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)

  useEffect(() => {
    fetch(apiUrl('/api/health'))
      .then((res) => (res.ok ? res.json() : Promise.reject()))
      .then((data: HealthResponse) => setBackendStatus(data.status === 'ok' ? 'ok' : 'error'))
      .catch(() => setBackendStatus('error'))
  }, [])

  const viewDocument = (jobId: string) => {
    setSelectedJobId(jobId)
    setPage('documents')
  }

  const openIssues = () => {
    setIssuesTab('problems')
    setPage('issues')
  }

  const openDuplicates = () => {
    setIssuesTab('duplicates')
    setPage('issues')
  }

  const { title, subtitle } = PAGE_TITLES[page]
  const { email, signOut } = useAuth()

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">FI</span>
          <div>
            <p className="brand-title">FinIntel</p>
            <p className="brand-sub">Document Intelligence</p>
          </div>
        </div>
        <nav className="side-nav" aria-label="Workspace">
          {NAV.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`nav-item ${page === item.id ? 'active' : ''}`}
              onClick={() => setPage(item.id)}
            >
              <NavIcon id={item.id} />
              {item.label}
            </button>
          ))}
        </nav>
        {email ? (
          <div className="sidebar-footer">
            <div className="user-block">
              <span className="user-avatar">{initials(email)}</span>
              <div>
                <p className="user-email">{email}</p>
                <p className="brand-sub">avaipl.com</p>
              </div>
            </div>
            <button type="button" className="signout-btn" onClick={() => void signOut()}>
              Sign out
            </button>
          </div>
        ) : null}
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <p className="eyebrow">FinIntel</p>
            <h1>{title}</h1>
            <p>{subtitle}</p>
          </div>
          <div className="topbar-actions">
            <div className={`status-pill status-${backendStatus}`}>
              <span className="status-dot" />
              {backendStatus === 'loading' ? 'Connecting' : backendStatus === 'ok' ? 'System online' : 'System offline'}
            </div>
          </div>
        </header>

        <TopAlerts
          refreshKey={docRefreshKey}
          onOpenIssues={openIssues}
          onOpenDuplicates={openDuplicates}
        />

        {page === 'dashboard' && (
          <Dashboard
            refreshKey={docRefreshKey}
            onOpenIssues={openIssues}
            onNavigate={(next) => {
              if (next === 'issues') openIssues()
              else setPage(next)
            }}
          />
        )}
        {page === 'documents' && (
          <Documents
            refreshKey={docRefreshKey}
            selectedJobId={selectedJobId}
            onSelectJob={setSelectedJobId}
            onDocumentDeleted={() => {
              setSelectedJobId(null)
              setDocRefreshKey((k) => k + 1)
            }}
          />
        )}
        {page === 'upload' && (
          <Upload
            onUploadComplete={() => setDocRefreshKey((k) => k + 1)}
            onViewDocument={viewDocument}
          />
        )}
        {page === 'issues' && (
          <>
            <div className="issues-tabs">
              <button
                type="button"
                className={`issues-tab ${issuesTab === 'problems' ? 'active' : ''}`}
                onClick={() => setIssuesTab('problems')}
              >
                Extraction problems
              </button>
              <button
                type="button"
                className={`issues-tab ${issuesTab === 'duplicates' ? 'active' : ''}`}
                onClick={() => setIssuesTab('duplicates')}
              >
                Duplicate uploads
              </button>
            </div>
            {issuesTab === 'problems' ? (
              <Issues refreshKey={docRefreshKey} onViewDocument={viewDocument} />
            ) : (
              <DuplicatesPanel refreshKey={docRefreshKey} onViewDocument={viewDocument} />
            )}
          </>
        )}
        {page === 'search' && <Search />}
      </main>
    </div>
  )
}

export default App
