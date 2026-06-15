import { useEffect, useState } from 'react'
import {
  type DuplicatesSummary,
  type QualitySummary,
  fetchDuplicatesSummary,
  fetchQualitySummary,
} from '../lib/quality'

type Props = {
  refreshKey: number
  onOpenIssues: () => void
  onOpenDuplicates: () => void
}

export function TopAlerts({ refreshKey, onOpenIssues, onOpenDuplicates }: Props) {
  const [quality, setQuality] = useState<QualitySummary | null>(null)
  const [duplicates, setDuplicates] = useState<DuplicatesSummary | null>(null)

  useEffect(() => {
    Promise.all([
      fetchQualitySummary().catch(() => null),
      fetchDuplicatesSummary().catch(() => null),
    ]).then(([q, d]) => {
      setQuality(q)
      setDuplicates(d)
    })
  }, [refreshKey])

  const issueCount = quality?.not_verified?.length ?? 0
  const layoutCount = quality?.layout_alert_count ?? 0
  const dupCount = duplicates?.duplicate_file_count ?? 0

  if (!quality && !duplicates) return null
  if (issueCount === 0 && dupCount === 0 && layoutCount === 0 && quality?.all_verified) {
    return (
      <div className="top-alerts top-alerts-ok">
        <span className="top-alert-pill top-alert-success">
          ✓ All {quality?.total ?? 0} documents verified — {quality?.verified_percent ?? 100}% quality pass
        </span>
      </div>
    )
  }

  return (
    <div className="top-alerts">
      {quality && layoutCount > 0 && (
        <button type="button" className="top-alert-pill top-alert-warn" onClick={onOpenIssues}>
          📋 {layoutCount} layout alert{layoutCount === 1 ? '' : 's'} — new or non-standard template
        </button>
      )}
      {quality && !quality.all_verified && issueCount > 0 && (
        <button type="button" className="top-alert-pill top-alert-warn" onClick={onOpenIssues}>
          ⚠ {issueCount} document{issueCount === 1 ? '' : 's'} need attention — see why &amp; how to fix
        </button>
      )}
      {quality && (
        <span className="top-alert-pill top-alert-info">
          Quality: {quality.verified}/{quality.total} verified ({quality.verified_percent}%)
        </span>
      )}
      {dupCount > 0 && (
        <button type="button" className="top-alert-pill top-alert-duplicate" onClick={onOpenDuplicates}>
          ↺ {dupCount} duplicate upload{dupCount === 1 ? '' : 's'} detected
        </button>
      )}
    </div>
  )
}

export function DuplicatesPanel({
  refreshKey,
  onViewDocument,
}: {
  refreshKey: number
  onViewDocument: (jobId: string) => void
}) {
  const [data, setData] = useState<DuplicatesSummary | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    fetchDuplicatesSummary()
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [refreshKey])

  const groups = [
    ...(data?.exact_duplicate_groups ?? []).map((g) => ({ ...g, label: 'Exact same file' })),
    ...(data?.filename_duplicate_groups ?? []).map((g) => ({ ...g, label: 'Same file name' })),
  ]

  return (
    <section className="panel">
      <h2>Duplicate Uploads</h2>
      <p className="muted table-subtitle">
        Files uploaded more than once. Upload #1 is the first time; #2, #3, etc. are repeat uploads.
      </p>

      {loading && <p className="muted">Scanning for duplicates…</p>}

      {!loading && groups.length === 0 && (
        <div className="issues-empty success-box">
          <p><strong>No duplicate uploads found.</strong></p>
          <p className="muted">Each file in the library appears to be unique.</p>
        </div>
      )}

      <div className="issues-list">
        {groups.map((group) => (
          <article key={`${group.match_type}-${group.file_name}`} className="issue-card">
            <div className="issue-card-header">
              <div>
                <h3 className="issue-file-name">{group.file_name}</h3>
                <p className="muted">{group.label} · {group.count} uploads</p>
              </div>
              <span className="badge badge-duplicate">{group.count}×</span>
            </div>
            <ul className="duplicate-upload-list">
              {group.uploads.map((upload) => (
                <li key={upload.job_id}>
                  <span className="duplicate-upload-badge">Upload #{upload.upload_number}</span>
                  <span>{new Date(upload.uploaded_at).toLocaleString('en-IN')}</span>
                  <button type="button" className="link-btn" onClick={() => onViewDocument(upload.job_id)}>
                    View
                  </button>
                </li>
              ))}
            </ul>
          </article>
        ))}
      </div>
    </section>
  )
}
