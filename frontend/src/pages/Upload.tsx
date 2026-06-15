import { useCallback, useRef, useState } from 'react'
import {
  ACCEPTED_UPLOAD_ACCEPT,
  ACCEPTED_UPLOAD_LABEL,
  collectDroppedFiles,
  collectInputFiles,
  displayFileName,
} from '../lib/upload'
import { QualityBadge, dataQualityClass } from '../lib/quality'

const UPLOAD_CONCURRENCY = 5

type UploadResult = {
  job_id: string
  status: string
  file_name: string
  is_duplicate?: boolean
  duplicate_upload_number?: number
  duplicate_message?: string
  extraction_status?: string
  extraction_status_label?: string
  extraction_status_symbol?: string
  extraction_issues?: string[]
  data_quality?: string
  profile_matched?: boolean
  profile_alerts?: string[]
  upload_error?: string
}

type BatchSummary = {
  total: number
  saved: number
  verified: number
  layoutAlerts: number
  failed: number
}

type Props = {
  onUploadComplete: () => void
  onViewDocument?: (jobId: string) => void
}

async function uploadOneFile(file: File): Promise<UploadResult> {
  const formData = new FormData()
  formData.append('file', file)

  const res = await fetch('/api/v1/upload', {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) {
    const detail = await res.text()
    return {
      job_id: '',
      status: 'error',
      file_name: displayFileName(file),
      upload_error: detail || `Failed to upload ${displayFileName(file)}`,
    }
  }

  const data = await res.json()
  return {
    job_id: data.job_id,
    status: data.status,
    file_name: displayFileName(file),
    is_duplicate: data.is_duplicate,
    duplicate_upload_number: data.duplicate_upload_number,
    duplicate_message: data.duplicate_message,
    extraction_status: data.extraction_status,
    extraction_status_label: data.extraction_status_label,
    extraction_status_symbol: data.extraction_status_symbol,
    extraction_issues: data.extraction_issues,
    data_quality: data.data_quality,
    profile_matched: data.profile_matched,
    profile_alerts: data.profile_alerts,
  }
}

async function runUploadPool(files: File[], concurrency: number, onProgress: (n: number) => void) {
  const results: UploadResult[] = new Array(files.length)
  let nextIndex = 0
  let completed = 0

  async function worker() {
    while (nextIndex < files.length) {
      const i = nextIndex
      nextIndex += 1
      results[i] = await uploadOneFile(files[i])
      completed += 1
      onProgress(completed)
    }
  }

  const workers = Array.from({ length: Math.min(concurrency, files.length) }, () => worker())
  await Promise.all(workers)
  return results
}

function summarizeBatch(results: UploadResult[]): BatchSummary {
  const saved = results.filter((r) => r.job_id && !r.upload_error).length
  const verified = results.filter((r) => r.extraction_status === 'verified').length
  const layoutAlerts = results.filter((r) => r.profile_matched === false).length
  const failed = results.filter(
    (r) => r.upload_error || r.extraction_status === 'failed',
  ).length
  return { total: results.length, saved, verified, layoutAlerts, failed }
}

export function Upload({ onUploadComplete, onViewDocument }: Props) {
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState<{ current: number; total: number } | null>(null)
  const [results, setResults] = useState<UploadResult[]>([])
  const [batchSummary, setBatchSummary] = useState<BatchSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const folderInputRef = useRef<HTMLInputElement>(null)

  const processFiles = useCallback(
    async (files: File[]) => {
      const fileArray = collectInputFiles(files)
      if (fileArray.length === 0) {
        setError(`No supported files found. Accepted: ${ACCEPTED_UPLOAD_LABEL}`)
        return
      }

      setUploading(true)
      setError(null)
      setBatchSummary(null)
      setProgress({ current: 0, total: fileArray.length })

      const batchResults = await runUploadPool(fileArray, UPLOAD_CONCURRENCY, (current) => {
        setProgress({ current, total: fileArray.length })
      })

      setResults((prev) => [...batchResults, ...prev])
      setBatchSummary(summarizeBatch(batchResults))

      const hardErrors = batchResults.filter((r) => r.upload_error)
      if (hardErrors.length === batchResults.length) {
        setError('All uploads failed. Check the server is running and files are valid PDFs.')
      } else if (hardErrors.length > 0) {
        setError(`${hardErrors.length} file(s) could not be saved — the rest completed successfully.`)
      }

      setUploading(false)
      setProgress(null)
      onUploadComplete()

      if (fileInputRef.current) fileInputRef.current.value = ''
      if (folderInputRef.current) folderInputRef.current.value = ''
    },
    [onUploadComplete],
  )

  const onDrop = useCallback(
    async (e: React.DragEvent) => {
      e.preventDefault()
      setDragging(false)
      try {
        const files = await collectDroppedFiles(e.dataTransfer)
        await processFiles(files)
      } catch {
        setError('Could not read dropped folder. Try Browse folder instead.')
      }
    },
    [processFiles],
  )

  return (
    <>
      <section
        className={`upload-zone ${dragging ? 'upload-zone-active' : ''}`}
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <div className="upload-icon">↑</div>
        <h2>Drag & drop files or folders here</h2>
        <p className="muted">
          {ACCEPTED_UPLOAD_LABEL} — up to {UPLOAD_CONCURRENCY} files process at once; layout mismatches
          only raise an alert
        </p>

        <div className="upload-btn-row">
          <label className="upload-btn">
            Browse files
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept={ACCEPTED_UPLOAD_ACCEPT}
              hidden
              disabled={uploading}
              onChange={(e) => e.target.files && processFiles(Array.from(e.target.files))}
            />
          </label>

          <label className="upload-btn upload-btn-secondary">
            Browse folder
            <input
              ref={folderInputRef}
              type="file"
              multiple
              accept={ACCEPTED_UPLOAD_ACCEPT}
              hidden
              disabled={uploading}
              // @ts-expect-error webkitdirectory is supported in Chromium browsers
              webkitdirectory=""
              directory=""
              onChange={(e) => e.target.files && processFiles(Array.from(e.target.files))}
            />
          </label>
        </div>

        {uploading && progress && (
          <p className="upload-status">
            Processing {progress.current} of {progress.total} in parallel…
          </p>
        )}
      </section>

      {error && <p className="error-text">{error}</p>}

      {batchSummary && !uploading && (
        <section className="panel panel-warn upload-batch-summary">
          <h2>Batch complete</h2>
          <p className="muted table-subtitle">
            Every file is saved to the backend. Only mismatched layouts get an alert — other files are
            not blocked.
          </p>
          <ul className="upload-batch-stats">
            <li>
              <strong>{batchSummary.saved}</strong> / {batchSummary.total} saved
            </li>
            <li>
              <strong>{batchSummary.verified}</strong> verified
            </li>
            {batchSummary.layoutAlerts > 0 && (
              <li className="warning-text">
                <strong>{batchSummary.layoutAlerts}</strong> layout alert
                {batchSummary.layoutAlerts === 1 ? '' : 's'} — check Issues page
              </li>
            )}
            {batchSummary.failed > 0 && (
              <li className="error-text">
                <strong>{batchSummary.failed}</strong> need attention
              </li>
            )}
          </ul>
        </section>
      )}

      {results.length > 0 && (
        <section className="panel">
          <h2>Recent Uploads ({results.length})</h2>
          <ul className="upload-list">
            {results.map((r, index) => (
              <li key={r.job_id || `${r.file_name}-${index}`} className="upload-result-item">
                <div className="upload-result-main">
                  <span className="upload-file-name">{r.file_name}</span>
                  {r.is_duplicate && (
                    <span className="badge badge-duplicate" title={r.duplicate_message}>
                      Upload #{r.duplicate_upload_number ?? 2} — duplicate
                    </span>
                  )}
                  {r.profile_matched === false && (
                    <span className="badge badge-warning" title={(r.profile_alerts ?? []).join(' · ')}>
                      Layout alert
                    </span>
                  )}
                </div>
                <div className="upload-actions">
                  {r.upload_error ? (
                    <span className="badge badge-failed">Upload error</span>
                  ) : (
                    <>
                      {r.extraction_status && (
                        <QualityBadge
                          status={r.extraction_status}
                          label={r.extraction_status_label}
                          symbol={r.extraction_status_symbol}
                          title={(r.extraction_issues ?? []).join(' · ')}
                        />
                      )}
                      {r.data_quality && (
                        <span className={`data-quality-mark ${dataQualityClass(r.data_quality)}`}>
                          {r.data_quality}
                        </span>
                      )}
                      <span className={`badge badge-${r.status}`}>{r.status}</span>
                      {onViewDocument && r.job_id && (
                        <button type="button" className="link-btn" onClick={() => onViewDocument(r.job_id)}>
                          View data
                        </button>
                      )}
                    </>
                  )}
                </div>
                {r.upload_error && <p className="error-text upload-issue-msg">{r.upload_error}</p>}
                {r.duplicate_message && (
                  <p className="muted upload-duplicate-msg">{r.duplicate_message}</p>
                )}
                {(r.profile_alerts?.length ?? 0) > 0 && (
                  <p className="warning-text upload-issue-msg">{(r.profile_alerts ?? []).join(' · ')}</p>
                )}
                {(r.extraction_issues?.length ?? 0) > 0 && !r.profile_alerts?.length && (
                  <p className="warning-text upload-issue-msg">
                    {(r.extraction_issues ?? []).join(' · ')}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  )
}
