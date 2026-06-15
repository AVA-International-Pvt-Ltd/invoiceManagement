import { useEffect, useState } from 'react'
import {
  QualityBadge,
  type QualityDocument,
  type QualitySummary,
  fetchQualitySummary,
} from '../lib/quality'
import { formatUploadDate } from '../lib/documents'

type Props = {
  refreshKey?: number
  onViewDocument: (jobId: string) => void
}

export function Issues({ refreshKey = 0, onViewDocument }: Props) {
  const [summary, setSummary] = useState<QualitySummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<'all' | 'failed' | 'needs_review'>('all')

  useEffect(() => {
    setLoading(true)
    fetchQualitySummary()
      .then(setSummary)
      .catch(() => setSummary(null))
      .finally(() => setLoading(false))
  }, [refreshKey])

  const problemDocs = (summary?.not_verified ?? []).filter((doc) => {
    if (filter === 'all') return true
    return doc.status === filter
  })

  return (
    <>
      <section className="metrics">
        <article className="metric-card">
          <p className="metric-label">Total Documents</p>
          <p className="metric-value">{summary?.total ?? '—'}</p>
        </article>
        <article className="metric-card metric-card-success">
          <p className="metric-label">Verified ✓</p>
          <p className="metric-value">{summary?.verified ?? '—'}</p>
        </article>
        <article className="metric-card metric-card-warn">
          <p className="metric-label">Review Suggested ⚠</p>
          <p className="metric-value">{summary?.needs_review ?? '—'}</p>
        </article>
        <article className="metric-card metric-card-error">
          <p className="metric-label">Failed ✕</p>
          <p className="metric-value">{summary?.failed ?? '—'}</p>
        </article>
      </section>

      <section className="panel">
        <div className="panel-header-row">
          <div>
            <h2>Extraction Problems</h2>
            <p className="muted table-subtitle">
              Why extraction may be incomplete and how to fix it. Only documents that need attention are listed below.
            </p>
          </div>
          <div className="filter-row">
            <select value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)}>
              <option value="all">All issues</option>
              <option value="failed">Failed only</option>
              <option value="needs_review">Review suggested</option>
            </select>
          </div>
        </div>

        {loading && <p className="muted">Loading quality report…</p>}

        {!loading && summary?.all_verified && (
          <div className="issues-empty success-box">
            <p><strong>All {summary.total} documents are verified.</strong></p>
            <p className="muted">No extraction problems detected. You can export with confidence.</p>
          </div>
        )}

        {!loading && !summary?.all_verified && problemDocs.length === 0 && (
          <p className="muted">No documents match this filter.</p>
        )}

        <div className="issues-list">
          {problemDocs.map((doc) => (
            <IssueCard key={doc.job_id} doc={doc} onView={() => onViewDocument(doc.job_id)} />
          ))}
        </div>
      </section>
    </>
  )
}

function IssueCard({ doc, onView }: { doc: QualityDocument; onView: () => void }) {
  const details = doc.issues_detailed?.length
    ? doc.issues_detailed
    : (doc.issues ?? []).map((issue) => ({ issue, how_to_fix: 'Re-upload a clearer PDF or review line items manually.' }))

  return (
    <article className="issue-card">
      <div className="issue-card-header">
        <div>
          <h3 className="issue-file-name">{doc.file_name || doc.job_id}</h3>
          <p className="muted issue-meta">
            Uploaded {formatUploadDate(doc.uploaded_at)}
          </p>
        </div>
        <QualityBadge
          status={doc.status}
          label={doc.status_label}
          symbol={doc.status_symbol}
        />
      </div>

      <div className="issue-details">
        {details.map((item, index) => (
          <div key={`${doc.job_id}-${index}`} className="issue-detail-block">
            <p className="issue-why">
              <strong>Why:</strong> {item.issue}
            </p>
            <p className="issue-fix">
              <strong>How to fix:</strong> {item.how_to_fix}
            </p>
          </div>
        ))}
      </div>

      <button type="button" className="secondary-btn" onClick={onView}>
        Open document
      </button>
    </article>
  )
}
