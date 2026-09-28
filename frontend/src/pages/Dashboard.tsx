import { useEffect, useState } from 'react'
import { apiFetch } from '../lib/api'
import { fetchQualitySummary, type QualitySummary } from '../lib/quality'

type JobSummary = {
  document_type?: string
  grand_total?: number
  line_item_count?: number
  extraction_status?: string
  data_quality?: string
}

type Props = {
  refreshKey?: number
  onOpenIssues?: () => void
  onNavigate?: (page: 'documents' | 'upload' | 'search' | 'issues') => void
}

export function Dashboard({ refreshKey = 0, onOpenIssues, onNavigate }: Props) {
  const [jobs, setJobs] = useState<JobSummary[]>([])
  const [quality, setQuality] = useState<QualitySummary | null>(null)

  useEffect(() => {
    apiFetch('/api/v1/jobs')
      .then((res) => res.json())
      .then((data) => setJobs(data.jobs ?? []))
      .catch(() => setJobs([]))
    fetchQualitySummary()
      .then(setQuality)
      .catch(() => setQuality(null))
  }, [refreshKey])

  const totalValue = jobs.reduce((sum, job) => sum + (job.grand_total ?? 0), 0)
  const creditNotes = jobs.filter((j) => j.document_type === 'credit_note').length
  const lineItems = jobs.reduce((sum, job) => sum + (job.line_item_count ?? 0), 0)

  const avgDataQuality = (() => {
    const scores = jobs
      .map((j) => parseInt(String(j.data_quality || '0').replace('%', ''), 10))
      .filter((n) => !Number.isNaN(n))
    if (!scores.length) return '—'
    return `${Math.round(scores.reduce((a, b) => a + b, 0) / scores.length)}%`
  })()

  return (
    <>
      <section className="metrics">
        <article className="metric-card">
          <p className="metric-label">Total Documents</p>
          <p className="metric-value">{jobs.length}</p>
        </article>
        <article className="metric-card">
          <p className="metric-label">Invoice Value</p>
          <p className="metric-value">₹{totalValue.toLocaleString('en-IN')}</p>
        </article>
        <article className="metric-card metric-card-success">
          <p className="metric-label">Verified</p>
          <p className="metric-value">
            {quality ? `${quality.verified}/${quality.total}` : '—'}
          </p>
        </article>
        <article className="metric-card">
          <p className="metric-label">Avg Data Quality</p>
          <p className="metric-value">{avgDataQuality}</p>
        </article>
        <article className="metric-card">
          <p className="metric-label">Credit Notes</p>
          <p className="metric-value">{creditNotes}</p>
        </article>
        <article className="metric-card">
          <p className="metric-label">Line Items</p>
          <p className="metric-value">{lineItems}</p>
        </article>
      </section>

      {quality && !quality.all_verified && onOpenIssues && (
        <section className="panel panel-warn">
          <h2>Quality attention needed</h2>
          <p>
            {quality.not_verified.length} document{quality.not_verified.length === 1 ? '' : 's'} need review
            ({quality.failed} failed, {quality.needs_review} review suggested).
          </p>
          <button type="button" className="secondary-btn" onClick={onOpenIssues}>
            View issues &amp; fixes
          </button>
        </section>
      )}

      <section className="panel">
        <h2>How the workspace is used</h2>
        <p className="muted table-subtitle">Four steps from a PDF to a file the accounts team can export.</p>
        <div className="workflow">
          <button type="button" className="workflow-card" onClick={() => onNavigate?.('upload')}>
            <span className="workflow-step">01</span>
            <strong>Ingest</strong>
            <span>Drop invoices, credit notes, and R4C files. Folders are accepted.</span>
          </button>
          <button type="button" className="workflow-card" onClick={() => onNavigate?.('documents')}>
            <span className="workflow-step">02</span>
            <strong>Review</strong>
            <span>Open a document, check line items, and confirm totals.</span>
          </button>
          <button type="button" className="workflow-card" onClick={() => onOpenIssues?.()}>
            <span className="workflow-step">03</span>
            <strong>Resolve</strong>
            <span>Clear failed extractions and duplicate uploads before close.</span>
          </button>
          <button type="button" className="workflow-card" onClick={() => onNavigate?.('search')}>
            <span className="workflow-step">04</span>
            <strong>Find</strong>
            <span>Look up an invoice number, vendor, or GSTIN across the library.</span>
          </button>
        </div>
      </section>
    </>
  )
}
