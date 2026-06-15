const MONTHS: Record<string, number> = {
  jan: 0,
  feb: 1,
  mar: 2,
  apr: 3,
  may: 4,
  jun: 5,
  jul: 6,
  aug: 7,
  sep: 8,
  oct: 9,
  nov: 10,
  dec: 11,
}

/** Parse document dates like 23-Nov-2025 or 09-MAR-2026. */
export function parseDocDate(value?: string): Date | null {
  if (!value?.trim()) return null

  const iso = Date.parse(value)
  if (!Number.isNaN(iso)) return new Date(iso)

  const match = value.trim().match(/^(\d{1,2})-([A-Za-z]{3})-(\d{4})$/i)
  if (!match) return null

  const day = Number(match[1])
  const month = MONTHS[match[2].toLowerCase()]
  const year = Number(match[3])
  if (month === undefined) return null

  return new Date(year, month, day)
}

export function formatDocDate(value?: string): string {
  const parsed = parseDocDate(value)
  if (!parsed) return value?.trim() || '—'
  return parsed.toLocaleDateString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

export function formatCurrency(value?: number): string {
  if (value === undefined || value === null || Number.isNaN(value)) return '—'
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    minimumFractionDigits: 2,
  }).format(value)
}

export type SourceFilter = 'all' | 'clicktech' | 'etrade'
export type SubtypeFilter = 'all' | 'invoice' | 'r4c' | 'credit_note' | 'cancellation'
export type UploadFilter = 'all' | 'today' | 'yesterday' | 'custom'
export type QualityFilter = 'all' | 'verified' | 'needs_review' | 'failed'

export type JobSummary = {
  job_id: string
  status: string
  file_name?: string
  document_type?: string
  document_subtype?: string
  document_subtype_label?: string
  document_heading?: string
  source?: string
  source_label?: string
  extraction_status?: 'verified' | 'needs_review' | 'failed'
  extraction_status_label?: string
  extraction_status_symbol?: string
  extraction_issues?: string[]
  data_quality?: string
  profile_matched?: boolean
  profile_alerts?: string[]
  content_hash?: string
  document_number?: string
  document_date?: string
  uploaded_at?: string
  system_ref_no?: string
  customer?: string
  invoice_number?: string
  vendor?: string
  line_item_count?: number
  quantity_total?: number
  grand_total?: number
  place_of_supply?: string
  reason?: string
}

function startOfDay(date: Date): Date {
  const d = new Date(date)
  d.setHours(0, 0, 0, 0)
  return d
}

export function parseUploadedAt(value?: string): Date | null {
  if (!value?.trim()) return null
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

export function formatUploadDate(value?: string): string {
  const parsed = parseUploadedAt(value)
  if (!parsed) return '—'
  return parsed.toLocaleString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function matchesUploadFilter(
  uploadedAt: string | undefined,
  filter: UploadFilter,
  customDate = '',
): boolean {
  if (filter === 'all') return true

  const parsed = parseUploadedAt(uploadedAt)
  if (!parsed) return false

  const uploadedDay = startOfDay(parsed).getTime()
  const today = startOfDay(new Date()).getTime()

  if (filter === 'today') return uploadedDay === today

  if (filter === 'yesterday') {
    const yesterday = new Date(today)
    yesterday.setDate(yesterday.getDate() - 1)
    return uploadedDay === yesterday.getTime()
  }

  if (filter === 'custom') {
    if (!customDate) return true
    const picked = startOfDay(new Date(`${customDate}T00:00:00`)).getTime()
    return uploadedDay === picked
  }

  return true
}

export function sourceLabel(source?: string): string {
  if (source === 'clicktech') return 'Clicktech'
  if (source === 'etrade') return 'ETRADE'
  return 'Unknown'
}

/** True when extraction did not pass all quality checks (not export-ready). */
export function didNotPassCriteria(job: JobSummary): boolean {
  return job.extraction_status !== 'verified'
}

export function criteriaStatusLabel(status?: JobSummary['extraction_status']): string {
  if (status === 'failed') return 'Failed — data unreliable'
  if (status === 'needs_review') return 'Review suggested — may be incomplete'
  return 'Verified'
}

export function matchesFilters(
  job: JobSummary,
  opts: {
    source: SourceFilter
    subtype: SubtypeFilter
    upload: UploadFilter
    uploadCustomDate: string
    dateFrom: string
    dateTo: string
    search: string
    quality: QualityFilter
  },
): boolean {
  if (opts.source !== 'all' && job.source !== opts.source) return false

  if (opts.subtype !== 'all' && job.document_subtype !== opts.subtype) return false

  if (opts.quality !== 'all' && job.extraction_status !== opts.quality) return false

  if (!matchesUploadFilter(job.uploaded_at, opts.upload, opts.uploadCustomDate)) return false

  const docDate = parseDocDate(job.document_date)
  if (opts.dateFrom) {
    const from = new Date(opts.dateFrom)
    from.setHours(0, 0, 0, 0)
    if (!docDate || docDate < from) return false
  }
  if (opts.dateTo) {
    const to = new Date(opts.dateTo)
    to.setHours(23, 59, 59, 999)
    if (!docDate || docDate > to) return false
  }

  const q = opts.search.trim().toLowerCase()
  if (q) {
    const haystack = [
      job.file_name,
      job.document_number,
      job.system_ref_no,
      job.customer,
      job.vendor,
      job.document_heading,
      job.document_subtype_label,
      job.source_label,
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()
    if (!haystack.includes(q)) return false
  }

  return true
}

export async function downloadSelectedXlsx(jobIds: string[]): Promise<void> {
  const res = await fetch('/api/v1/export/xlsx/selected', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_ids: jobIds }),
  })
  if (!res.ok) throw new Error('Export failed')

  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'selected_documents_extracted.xlsx'
  anchor.click()
  URL.revokeObjectURL(url)
}

export async function downloadAllXlsx(): Promise<void> {
  const res = await fetch('/api/v1/export/xlsx')
  if (!res.ok) throw new Error('Export failed')

  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'all_documents_extracted.xlsx'
  anchor.click()
  URL.revokeObjectURL(url)
}
