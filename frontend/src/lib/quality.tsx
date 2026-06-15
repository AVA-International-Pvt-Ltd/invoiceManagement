export type ExtractionStatus = 'verified' | 'needs_review' | 'failed'

export type IssueDetail = {
  issue: string
  how_to_fix: string
}

export type QualityDocument = {
  job_id: string
  file_name: string
  status: ExtractionStatus
  status_label?: string
  status_symbol?: string
  issues?: string[]
  issues_detailed?: IssueDetail[]
  uploaded_at?: string
  profile_matched?: boolean
  profile_alerts?: string[]
}

export type QualitySummary = {
  total: number
  verified: number
  needs_review: number
  failed: number
  verified_percent: number
  all_verified: boolean
  layout_alert_count?: number
  not_verified: QualityDocument[]
  documents?: QualityDocument[]
}

export type DuplicateUpload = {
  job_id: string
  file_name: string
  uploaded_at: string
  upload_number: number
  invoice_number?: string
  vendor?: string
}

export type DuplicateGroup = {
  match_type: 'exact' | 'filename'
  file_name: string
  count: number
  uploads: DuplicateUpload[]
  content_hash?: string
}

export type DuplicatesSummary = {
  total_documents: number
  duplicate_file_count: number
  duplicate_group_count: number
  duplicate_job_ids?: string[]
  exact_duplicate_groups: DuplicateGroup[]
  filename_duplicate_groups: DuplicateGroup[]
}

export function collectDuplicateJobIds(summary: DuplicatesSummary | null | undefined): Set<string> {
  const ids = new Set<string>()
  if (!summary) return ids
  for (const id of summary.duplicate_job_ids ?? []) {
    ids.add(id)
  }
  for (const group of [...summary.exact_duplicate_groups, ...summary.filename_duplicate_groups]) {
    for (const upload of group.uploads.slice(1)) {
      ids.add(upload.job_id)
    }
  }
  return ids
}

export function qualityBadgeClass(status?: string): string {
  if (status === 'verified') return 'badge-quality-verified'
  if (status === 'needs_review') return 'badge-quality-needs_review'
  if (status === 'failed') return 'badge-quality-failed'
  return 'badge-type-unknown'
}

export function dataQualityClass(value?: string): string {
  const pct = parseInt(String(value || '0').replace('%', ''), 10)
  if (pct >= 90) return 'data-quality-high'
  if (pct >= 70) return 'data-quality-mid'
  return 'data-quality-low'
}

export async function fetchQualitySummary(): Promise<QualitySummary> {
  const res = await fetch('/api/v1/quality/summary')
  if (!res.ok) throw new Error('Failed to load quality summary')
  return res.json()
}

export async function fetchDuplicatesSummary(): Promise<DuplicatesSummary> {
  const res = await fetch('/api/v1/duplicates')
  if (!res.ok) throw new Error('Failed to load duplicates')
  return res.json()
}

export function QualityBadge({
  status,
  label,
  symbol,
  title,
}: {
  status?: ExtractionStatus | string
  label?: string
  symbol?: string
  title?: string
}) {
  if (!status) return null
  return (
    <span
      className={`badge badge-quality badge-quality-${status}`}
      title={title}
    >
      {symbol && <span className="badge-quality-icon">{symbol}</span>}
      <span className="badge-quality-text">{label || status}</span>
    </span>
  )
}
