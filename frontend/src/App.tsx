import { useEffect, useState } from 'react'
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
  { id: 'dashboard', label: 'Dashboard' },
  { id: 'documents', label: 'Documents' },
  { id: 'upload', label: 'Upload' },
  { id: 'issues', label: 'Issues & Quality' },
  { id: 'search', label: 'Search' },
]

const PAGE_TITLES: Record<Page, { title: string; subtitle: string }> = {
  dashboard: {
    title: 'Dashboard',
    subtitle: 'Enterprise Financial Document Intelligence Platform',
  },
  documents: {
    title: 'Documents',
    subtitle: 'View and manage processed financial documents',
  },
  upload: {
    title: 'Upload',
    subtitle: 'Ingest invoices, credit notes, R4C reports, and more',
  },
  issues: {
    title: 'Issues & Quality',
    subtitle: 'Extraction problems, duplicate uploads, and quality marks',
  },
  search: {
    title: 'Search',
    subtitle: 'Find documents by invoice number, vendor, GSTIN, and more',
  },
}

function App() {
  const [page, setPage] = useState<Page>('dashboard')
  const [issuesTab, setIssuesTab] = useState<IssuesTab>('problems')
  const [backendStatus, setBackendStatus] = useState<'loading' | 'ok' | 'error'>('loading')
  const [docRefreshKey, setDocRefreshKey] = useState(0)
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/health')
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
        <nav>
          {NAV.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`nav-item ${page === item.id ? 'active' : ''}`}
              onClick={() => setPage(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <h1>{title}</h1>
            <p>{subtitle}</p>
          </div>
          <div className={`status-pill status-${backendStatus}`}>
            Backend: {backendStatus === 'loading' ? 'Connecting…' : backendStatus === 'ok' ? 'Online' : 'Offline'}
          </div>
        </header>

        <TopAlerts
          refreshKey={docRefreshKey}
          onOpenIssues={openIssues}
          onOpenDuplicates={openDuplicates}
        />

        {page === 'dashboard' && <Dashboard refreshKey={docRefreshKey} onOpenIssues={openIssues} />}
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
