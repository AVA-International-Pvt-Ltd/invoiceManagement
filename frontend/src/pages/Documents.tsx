import { useEffect, useMemo, useState } from 'react'
import { DocumentDetail } from './DocumentDetail'
import {
  type JobSummary,
  type QualityFilter,
  type SourceFilter,
  type SubtypeFilter,
  type UploadFilter,
  downloadAllXlsx,
  downloadSelectedXlsx,
  formatCurrency,
  formatDocDate,
  formatUploadDate,
  didNotPassCriteria,
  matchesFilters,
  sourceLabel,
} from '../lib/documents'
import { collectDuplicateJobIds, dataQualityClass, fetchDuplicatesSummary } from '../lib/quality'

type Props = {
  refreshKey: number
  selectedJobId?: string | null
  onSelectJob?: (jobId: string | null) => void
  onDocumentDeleted?: () => void
}

export function Documents({ refreshKey, selectedJobId, onSelectJob, onDocumentDeleted }: Props) {
  const [jobs, setJobs] = useState<JobSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)
  const [bulkDeleting, setBulkDeleting] = useState(false)
  const [activeJobId, setActiveJobId] = useState<string | null>(selectedJobId ?? null)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [duplicateJobIds, setDuplicateJobIds] = useState<Set<string>>(new Set())
  const [duplicatesOnly, setDuplicatesOnly] = useState(false)
  const [failedCriteriaOnly, setFailedCriteriaOnly] = useState(false)

  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all')
  const [subtypeFilter, setSubtypeFilter] = useState<SubtypeFilter>('all')
  const [uploadFilter, setUploadFilter] = useState<UploadFilter>('all')
  const [uploadCustomDate, setUploadCustomDate] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [qualityFilter, setQualityFilter] = useState<QualityFilter>('all')
  const [search, setSearch] = useState('')

  const loadJobs = () => {
    setLoading(true)
    Promise.all([fetch('/api/v1/jobs').then((res) => res.json()), fetchDuplicatesSummary().catch(() => null)])
      .then(([jobsData, duplicatesData]) => {
        setJobs(jobsData.jobs ?? [])
        setDuplicateJobIds(collectDuplicateJobIds(duplicatesData))
      })
      .catch(() => {
        setJobs([])
        setDuplicateJobIds(new Set())
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    loadJobs()
  }, [refreshKey])

  useEffect(() => {
    if (selectedJobId) setActiveJobId(selectedJobId)
  }, [selectedJobId])

  const verifiedCount = useMemo(
    () => jobs.filter((job) => job.extraction_status === 'verified').length,
    [jobs],
  )
  const allVerified = jobs.length > 0 && verifiedCount === jobs.length

  const notVerifiedCount = useMemo(
    () => jobs.filter((job) => didNotPassCriteria(job)).length,
    [jobs],
  )

  const filteredJobs = useMemo(
    () =>
      jobs.filter((job) => {
        if (duplicatesOnly && !duplicateJobIds.has(job.job_id)) return false
        if (failedCriteriaOnly && !didNotPassCriteria(job)) return false
        return matchesFilters(job, {
          source: sourceFilter,
          subtype: subtypeFilter,
          upload: uploadFilter,
          uploadCustomDate,
          dateFrom,
          dateTo,
          search,
          quality: qualityFilter,
        })
      }),
    [
      jobs,
      duplicatesOnly,
      duplicateJobIds,
      failedCriteriaOnly,
      sourceFilter,
      subtypeFilter,
      uploadFilter,
      uploadCustomDate,
      dateFrom,
      dateTo,
      search,
      qualityFilter,
    ],
  )

  const duplicateVisibleCount = useMemo(
    () => jobs.filter((job) => duplicateJobIds.has(job.job_id)).length,
    [jobs, duplicateJobIds],
  )

  const filteredIds = useMemo(() => filteredJobs.map((job) => job.job_id), [filteredJobs])
  const allFilteredSelected =
    filteredIds.length > 0 && filteredIds.every((id) => selectedIds.has(id))
  const someFilteredSelected = filteredIds.some((id) => selectedIds.has(id))

  const openJob = (jobId: string) => {
    setActiveJobId(jobId)
    onSelectJob?.(jobId)
  }

  const toggleOne = (jobId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(jobId)) next.delete(jobId)
      else next.add(jobId)
      return next
    })
  }

  const toggleAllFiltered = () => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (allFilteredSelected) {
        filteredIds.forEach((id) => next.delete(id))
      } else {
        filteredIds.forEach((id) => next.add(id))
      }
      return next
    })
  }

  const clearFilters = () => {
    setSourceFilter('all')
    setSubtypeFilter('all')
    setUploadFilter('all')
    setUploadCustomDate('')
    setDateFrom('')
    setDateTo('')
    setSearch('')
    setQualityFilter('all')
    setDuplicatesOnly(false)
    setFailedCriteriaOnly(false)
  }

  const deleteJob = async (jobId: string, fileName?: string) => {
    const label = fileName || 'this document'
    if (
      !window.confirm(
        `Delete "${label}" completely?\n\nThis removes the JSON extraction, index entry, and uploaded file.`,
      )
    ) {
      return
    }

    setDeletingId(jobId)
    try {
      const res = await fetch(`/api/v1/jobs/${jobId}`, { method: 'DELETE' })
      if (!res.ok) throw new Error('Delete failed')

      if (activeJobId === jobId) setActiveJobId(null)
      onSelectJob?.(null)
      setJobs((prev) => prev.filter((job) => job.job_id !== jobId))
      setSelectedIds((prev) => {
        const next = new Set(prev)
        next.delete(jobId)
        return next
      })
      onDocumentDeleted?.()
      fetchDuplicatesSummary()
        .then((data) => setDuplicateJobIds(collectDuplicateJobIds(data)))
        .catch(() => undefined)
    } catch {
      window.alert('Failed to delete document. Please try again.')
    } finally {
      setDeletingId(null)
    }
  }

  const exportSelected = async () => {
    const ids = filteredIds.filter((id) => selectedIds.has(id))
    if (ids.length === 0) {
      window.alert('Select at least one document to export.')
      return
    }

    setExporting(true)
    try {
      await downloadSelectedXlsx(ids)
    } catch {
      window.alert('Failed to export selected documents.')
    } finally {
      setExporting(false)
    }
  }

  const exportAll = async () => {
    setExporting(true)
    try {
      await downloadAllXlsx()
    } catch {
      window.alert('Failed to export all documents.')
    } finally {
      setExporting(false)
    }
  }

  const deleteSelected = async () => {
    const ids = filteredIds.filter((id) => selectedIds.has(id))
    if (ids.length === 0) {
      window.alert('Select at least one document to delete.')
      return
    }

    const labels = ids
      .map((id) => jobs.find((job) => job.job_id === id)?.file_name ?? id)
      .slice(0, 5)
    const more = ids.length > 5 ? `\n…and ${ids.length - 5} more` : ''
    if (
      !window.confirm(
        `Delete ${ids.length} selected document${ids.length === 1 ? '' : 's'} completely?\n\n` +
          `This removes the JSON extraction, index entry, and uploaded file for each.\n\n` +
          labels.join('\n') +
          more,
      )
    ) {
      return
    }

    setBulkDeleting(true)
    const failed: string[] = []
    try {
      for (const jobId of ids) {
        const res = await fetch(`/api/v1/jobs/${jobId}`, { method: 'DELETE' })
        if (!res.ok) {
          failed.push(jobId)
          continue
        }
        if (activeJobId === jobId) setActiveJobId(null)
        setJobs((prev) => prev.filter((job) => job.job_id !== jobId))
        setSelectedIds((prev) => {
          const next = new Set(prev)
          next.delete(jobId)
          return next
        })
        setDuplicateJobIds((prev) => {
          const next = new Set(prev)
          next.delete(jobId)
          return next
        })
      }
      if (failed.length === 0) {
        onSelectJob?.(null)
        onDocumentDeleted?.()
        loadJobs()
      } else {
        window.alert(`Deleted ${ids.length - failed.length} of ${ids.length}. Some deletes failed.`)
        loadJobs()
      }
    } catch {
      window.alert('Failed to delete selected documents.')
      loadJobs()
    } finally {
      setBulkDeleting(false)
    }
  }

  return (
    <>
      <section className="panel documents-page-panel">
        <div className="panel-header-row">
          <div>
            <h2>Processed Documents</h2>
            <p className="muted table-subtitle">
              {filteredJobs.length} of {jobs.length} documents
              {jobs.length > 0 && (
                <>
                  {' · '}
                  <span className={allVerified ? 'quality-summary-ok' : 'quality-summary-warn'}>
                    {verifiedCount}/{jobs.length} verified
                    {allVerified ? ' (100%)' : ''}
                  </span>
                </>
              )}
              {selectedIds.size > 0 ? ` · ${selectedIds.size} selected` : ''}
              {duplicateVisibleCount > 0 ? ` · ${duplicateVisibleCount} duplicates` : ''}
              {notVerifiedCount > 0 ? (
                <>
                  {' · '}
                  <span className="quality-summary-warn">{notVerifiedCount} did not pass criteria</span>
                </>
              ) : null}
            </p>
          </div>
          <div className="table-action-group">
            <button
              type="button"
              className={`criteria-alert-btn${failedCriteriaOnly ? ' active' : ''}`}
              disabled={notVerifiedCount === 0}
              title={
                notVerifiedCount === 0
                  ? 'All documents passed quality checks'
                  : 'Show only documents that failed verification — totals, qty, or line items may be wrong'
              }
              onClick={() => setFailedCriteriaOnly((prev) => !prev)}
            >
              {failedCriteriaOnly ? '✕ Showing failed criteria' : `⚠ Failed Criteria (${notVerifiedCount})`}
            </button>
            <button
              type="button"
              className="delete-btn delete-selected-btn"
              disabled={bulkDeleting || deletingId !== null || selectedIds.size === 0}
              onClick={deleteSelected}
            >
              {bulkDeleting ? 'Deleting…' : `Delete Selected (${selectedIds.size})`}
            </button>
            <button
              type="button"
              className="secondary-btn"
              disabled={exporting || selectedIds.size === 0}
              onClick={exportSelected}
            >
              {exporting ? 'Exporting…' : `Export Selected (${selectedIds.size})`}
            </button>
            {jobs.length > 0 && (
              <button type="button" className="primary-btn" disabled={exporting} onClick={exportAll}>
                Export All XLSX
              </button>
            )}
          </div>
        </div>

        <div className="doc-filter-panel">
          <div className="doc-filter-header">
            <div>
              <h3 className="doc-filter-title">Filters</h3>
              <p className="doc-filter-subtitle muted">Narrow the document list by source, dates, quality, and more</p>
            </div>
            <button type="button" className="secondary-btn filter-clear-btn-compact" onClick={clearFilters}>
              Clear all
            </button>
          </div>

          <div className="doc-filter-body">
            <label className="filter-field filter-field-search">
              <span>Search</span>
              <input
                type="search"
                placeholder="File name, doc #, system ref…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </label>

            <div className="doc-filter-grid">
              <label className="filter-field">
                <span>Source</span>
                <select value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value as SourceFilter)}>
                  <option value="all">All sources</option>
                  <option value="clicktech">Clicktech</option>
                  <option value="etrade">ETRADE</option>
                </select>
              </label>

              <label className="filter-field">
                <span>Document type</span>
                <select value={subtypeFilter} onChange={(e) => setSubtypeFilter(e.target.value as SubtypeFilter)}>
                  <option value="all">All types</option>
                  <option value="invoice">GST Invoice</option>
                  <option value="r4c">Request for Credit</option>
                  <option value="credit_note">GST Credit Note</option>
                  <option value="cancellation">Cancellation of Request for Credit</option>
                </select>
              </label>

              <label className="filter-field">
                <span>Quality</span>
                <select
                  value={qualityFilter}
                  onChange={(e) => setQualityFilter(e.target.value as QualityFilter)}
                >
                  <option value="all">All quality</option>
                  <option value="verified">Verified only</option>
                  <option value="needs_review">Review suggested</option>
                  <option value="failed">Failed / unreliable</option>
                </select>
              </label>

              <label className="filter-field">
                <span>Uploaded</span>
                <select
                  value={uploadFilter}
                  onChange={(e) => {
                    const value = e.target.value as UploadFilter
                    setUploadFilter(value)
                    if (value !== 'custom') setUploadCustomDate('')
                  }}
                >
                  <option value="all">All days</option>
                  <option value="today">Today</option>
                  <option value="yesterday">Yesterday</option>
                  <option value="custom">Custom date</option>
                </select>
              </label>

              {uploadFilter === 'custom' && (
                <label className="filter-field">
                  <span>Upload date</span>
                  <input
                    type="date"
                    value={uploadCustomDate}
                    max={new Date().toISOString().slice(0, 10)}
                    onChange={(e) => setUploadCustomDate(e.target.value)}
                  />
                </label>
              )}

              <label className="filter-field">
                <span>Doc date from</span>
                <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
              </label>

              <label className="filter-field">
                <span>Doc date to</span>
                <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
              </label>
            </div>

            <div className="doc-filter-toggles" role="group" aria-label="Quick filters">
              <p className="doc-filter-toggles-label">Quick filters</p>
              <label className={`filter-toggle-chip${duplicatesOnly ? ' active' : ''}`}>
                <input
                  type="checkbox"
                  checked={duplicatesOnly}
                  onChange={(e) => setDuplicatesOnly(e.target.checked)}
                  disabled={duplicateVisibleCount === 0}
                />
                <span>Duplicates only ({duplicateVisibleCount})</span>
              </label>

              <label className={`filter-toggle-chip${failedCriteriaOnly ? ' active' : ''}`}>
                <input
                  type="checkbox"
                  checked={failedCriteriaOnly}
                  onChange={(e) => setFailedCriteriaOnly(e.target.checked)}
                  disabled={notVerifiedCount === 0}
                />
                <span>Failed criteria ({notVerifiedCount})</span>
              </label>
            </div>
          </div>
        </div>

        {failedCriteriaOnly && (
          <div className="criteria-filter-banner" role="status">
            <strong>Documents below did not pass quality criteria.</strong>
            <span className="muted">
              Line items, totals, or quantities may be incomplete or wrong — review manually or re-upload the PDF.
              Special layouts (split pages, footers, missing Sl. No.) often cause partial extraction.
            </span>
          </div>
        )}

        {loading ? (
          <p className="muted">Loading documents…</p>
        ) : jobs.length === 0 ? (
          <p className="muted">No documents yet. Go to Upload to process your first file.</p>
        ) : filteredJobs.length === 0 ? (
          <p className="muted">
            {failedCriteriaOnly
              ? 'No documents failed quality criteria — all extractions passed verification.'
              : 'No documents match your filters.'}
          </p>
        ) : (
          <div className="table-wrap">
            <table className="data-table documents-table">
              <thead>
                <tr>
                  <th className="col-select">
                    <input
                      type="checkbox"
                      className="row-checkbox"
                      checked={allFilteredSelected}
                      ref={(el) => {
                        if (el) el.indeterminate = someFilteredSelected && !allFilteredSelected
                      }}
                      onChange={toggleAllFiltered}
                      aria-label="Select all visible documents"
                    />
                  </th>
                  <th>File</th>
                  <th>Source</th>
                  <th>System Ref</th>
                  <th>Document title</th>
                  <th>Quality</th>
                  {failedCriteriaOnly && <th className="col-issues">Why not verified</th>}
                  <th title="100% = all extraction checks passed">Data Quality</th>
                  <th>Doc #</th>
                  <th>Doc date</th>
                  <th className="col-uploaded">Uploaded</th>
                  <th className="col-items">Items</th>
                  <th>Total</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredJobs.map((job) => {
                  const notVerified = didNotPassCriteria(job)
                  const rowClasses = [
                    activeJobId === job.job_id ? 'row-active' : 'row-clickable',
                    notVerified ? `row-criteria-${job.extraction_status ?? 'needs_review'}` : '',
                    failedCriteriaOnly && notVerified ? 'row-criteria-emphasis' : '',
                  ]
                    .filter(Boolean)
                    .join(' ')

                  return (
                  <tr
                    key={job.job_id}
                    className={rowClasses}
                    onClick={() => openJob(job.job_id)}
                  >
                    <td className="col-select" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        className="row-checkbox"
                        checked={selectedIds.has(job.job_id)}
                        onChange={() => toggleOne(job.job_id)}
                        aria-label={`Select ${job.file_name ?? job.job_id}`}
                      />
                    </td>
                    <td className="cell-file">
                      {job.file_name ?? '—'}
                      {duplicateJobIds.has(job.job_id) && (
                        <span className="badge badge-duplicate doc-duplicate-badge" title="Duplicate upload">
                          Duplicate
                        </span>
                      )}
                    </td>
                    <td>
                      <span className={`badge badge-source badge-source-${job.source ?? 'unknown'}`}>
                        {sourceLabel(job.source)}
                      </span>
                    </td>
                    <td>{job.system_ref_no || '—'}</td>
                    <td>
                      <span className={`badge badge-type badge-type-${job.document_subtype ?? 'unknown'}`}>
                        {job.document_heading ?? job.document_subtype_label ?? job.document_type ?? '—'}
                      </span>
                    </td>
                    <td>
                      <span
                        className={`badge badge-quality badge-quality-${job.extraction_status ?? 'needs_review'}`}
                        title={(job.extraction_issues ?? []).join(' · ') || job.extraction_status_label}
                      >
                        <span className="badge-quality-icon" aria-hidden="true">
                          {job.extraction_status_symbol ?? '⚠'}
                        </span>
                        <span className="badge-quality-text">
                          {job.extraction_status_label ?? 'Review suggested'}
                        </span>
                      </span>
                    </td>
                    {failedCriteriaOnly && (
                      <td className="cell-issues">
                        {(job.extraction_issues ?? []).length > 0 ? (
                          <ul className="issue-snippet-list">
                            {(job.extraction_issues ?? []).slice(0, 2).map((issue) => (
                              <li key={issue}>{issue}</li>
                            ))}
                          </ul>
                        ) : (
                          <span className="muted">See Issues &amp; Quality tab</span>
                        )}
                      </td>
                    )}
                    <td>
                      <span
                        className={`data-quality-mark ${dataQualityClass(job.data_quality)}`}
                        title={
                          job.extraction_status === 'verified'
                            ? '100% — extraction verified, all checks passed'
                            : 'Field completeness — see Issues & Quality for details'
                        }
                      >
                        {job.data_quality ?? '—'}
                      </span>
                    </td>
                    <td className="mono">{job.document_number || '—'}</td>
                    <td>{formatDocDate(job.document_date)}</td>
                    <td className="col-uploaded cell-uploaded">{formatUploadDate(job.uploaded_at)}</td>
                    <td className="col-items">{job.line_item_count ?? 0}</td>
                    <td className="cell-total">{formatCurrency(job.grand_total)}</td>
                    <td>
                      <span className={`badge badge-${job.status}`}>{job.status}</span>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="delete-btn"
                        disabled={deletingId === job.job_id}
                        onClick={(e) => {
                          e.stopPropagation()
                          deleteJob(job.job_id, job.file_name)
                        }}
                      >
                        {deletingId === job.job_id ? 'Deleting…' : 'Delete'}
                      </button>
                    </td>
                  </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <DocumentDetail
        jobId={activeJobId}
        jobSummary={jobs.find((j) => j.job_id === activeJobId) ?? null}
        onClose={() => setActiveJobId(null)}
        onDelete={(jobId, fileName) => deleteJob(jobId, fileName)}
        deleting={deletingId !== null}
      />
    </>
  )
}
