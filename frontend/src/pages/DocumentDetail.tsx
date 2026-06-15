import { useEffect, useState } from 'react'
import { AddressCard } from '../components/AddressCard'
import { QualityBadge, dataQualityClass } from '../lib/quality'

type LineItem = {
  system_ref_no?: string
  product?: string
  hsn?: string
  asin?: string
  ean?: string
  sku?: string
  combo?: string
  invoice_no?: string
  invoice_date?: string
  units?: string
  quantity?: number
  cost_per_unit?: number
  total_cost?: number
  tax_rate?: number
  tax_type?: string
  tax_amount?: number
  total_amount?: number
}

type DocumentData = {
  document_id: string
  document_type: string
  confidence: number
  header: Record<string, string>
  vendor: { name?: string; gstin?: string; pan?: string; address?: string }
  customer: { name?: string; gstin?: string; pan?: string; address?: string }
  billing_address?: Record<string, string>
  shipping_address?: Record<string, string>
  receiver_billing_address?: Record<string, string>
  receiver_shipping_address?: Record<string, string>
  line_items: LineItem[]
  tax_summary: Record<string, number>
  totals: Record<string, number>
  validation: { status: string; confidence: number; errors: string[]; warnings: string[] }
  raw_data: { pages: { page_number: number; raw_text: string }[] }
  audit: { file_name?: string; json_path?: string; saved_at?: string }
}

const LINE_ITEM_COLUMNS: { key: keyof LineItem; label: string }[] = [
  { key: 'system_ref_no', label: 'Sl. No' },
  { key: 'product', label: 'Item Description' },
  { key: 'hsn', label: 'HSN/SAC' },
  { key: 'asin', label: 'ASIN Code' },
  { key: 'ean', label: 'UPC/EAN' },
  { key: 'combo', label: 'Purchase Order No' },
  { key: 'invoice_no', label: 'Vendor Invoice No' },
  { key: 'invoice_date', label: 'Vendor Invoice Date' },
  { key: 'units', label: 'Unit/Code' },
  { key: 'quantity', label: 'Quantity' },
  { key: 'cost_per_unit', label: 'Rate' },
  { key: 'total_cost', label: 'Assessable Value' },
  { key: 'tax_rate', label: 'GST Rate(%)' },
  { key: 'tax_type', label: 'Tax Type' },
  { key: 'tax_amount', label: 'GST Value' },
  { key: 'total_amount', label: 'Total Amount' },
]

type Props = {
  jobId: string | null
  jobSummary?: {
    extraction_status?: string
    extraction_status_label?: string
    extraction_status_symbol?: string
    extraction_issues?: string[]
    data_quality?: string
  } | null
  onClose: () => void
  onDelete?: (jobId: string, fileName?: string) => void
  deleting?: boolean
}

function formatCell(value: string | number | undefined) {
  if (value === undefined || value === null || value === '') return '—'
  return value
}

type FlatColumn = { key: string; label: string }
type FlatRow = Record<string, string | number>

export function DocumentDetail({ jobId, jobSummary, onClose, onDelete, deleting }: Props) {
  const [doc, setDoc] = useState<DocumentData | null>(null)
  const [loading, setLoading] = useState(false)
  const [flatColumns, setFlatColumns] = useState<FlatColumn[]>([])
  const [flatRows, setFlatRows] = useState<FlatRow[]>([])
  const [exporting, setExporting] = useState(false)
  const [tab, setTab] = useState<'summary' | 'line_items' | 'flat' | 'raw'>('summary')

  useEffect(() => {
    if (!jobId) {
      setDoc(null)
      setFlatRows([])
      return
    }
    setLoading(true)
    Promise.all([
      fetch(`/api/v1/jobs/${jobId}`).then((res) => res.json()),
      fetch(`/api/v1/jobs/${jobId}/export/flat`).then((res) => res.json()),
    ])
      .then(([jobData, flatData]) => {
        setDoc(jobData.document ?? null)
        setFlatColumns(flatData.columns ?? [])
        setFlatRows(flatData.rows ?? [])
      })
      .catch(() => {
        setDoc(null)
        setFlatRows([])
      })
      .finally(() => setLoading(false))
  }, [jobId])

  const downloadXlsx = async () => {
    if (!jobId) return
    setExporting(true)
    try {
      const res = await fetch(`/api/v1/jobs/${jobId}/export/xlsx`)
      if (!res.ok) throw new Error('export failed')
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      const baseName = doc?.audit.file_name?.replace(/\.[^.]+$/, '') || 'document'
      anchor.href = url
      anchor.download = `${baseName}_extracted.xlsx`
      anchor.click()
      URL.revokeObjectURL(url)
    } catch {
      window.alert('Failed to export XLSX.')
    } finally {
      setExporting(false)
    }
  }

  if (!jobId) return null

  return (
    <section className="panel detail-panel">
      <div className="detail-header">
        <h2>Extracted Data</h2>
        <div className="detail-actions">
          {jobId && (
            <button type="button" className="primary-btn" disabled={exporting} onClick={downloadXlsx}>
              {exporting ? 'Exporting…' : 'Export XLSX'}
            </button>
          )}
          {onDelete && jobId && (
            <button
              type="button"
              className="delete-btn"
              disabled={deleting}
              onClick={() => onDelete(jobId, doc?.audit.file_name)}
            >
              Delete
            </button>
          )}
          <button type="button" className="link-btn" onClick={onClose}>
            Close
          </button>
        </div>
      </div>

      {loading && <p className="muted">Loading extraction…</p>}
      {!loading && !doc && <p className="muted">No extraction data found.</p>}

      {doc && (
        <>
          <div className="tab-row">
            <button type="button" className={tab === 'summary' ? 'tab active' : 'tab'} onClick={() => setTab('summary')}>
              Summary
            </button>
            <button type="button" className={tab === 'line_items' ? 'tab active' : 'tab'} onClick={() => setTab('line_items')}>
              Line Items ({doc.line_items.length})
            </button>
            <button type="button" className={tab === 'flat' ? 'tab active' : 'tab'} onClick={() => setTab('flat')}>
              Flat Export ({flatRows.length})
            </button>
            <button type="button" className={tab === 'raw' ? 'tab active' : 'tab'} onClick={() => setTab('raw')}>
              Raw Text
            </button>
          </div>

          {tab === 'summary' && (
            <>
              {jobSummary && (
                <div className="detail-quality-row">
                  <QualityBadge
                    status={jobSummary.extraction_status}
                    label={jobSummary.extraction_status_label}
                    symbol={jobSummary.extraction_status_symbol}
                    title={(jobSummary.extraction_issues ?? []).join(' · ')}
                  />
                  {jobSummary.data_quality && (
                    <span className={`data-quality-mark ${dataQualityClass(jobSummary.data_quality)}`}>
                      Data quality: {jobSummary.data_quality}
                    </span>
                  )}
                </div>
              )}

              {(jobSummary?.extraction_issues?.length ?? 0) > 0 && (
                <div className="panel inset-panel">
                  <h3>Extraction issues</h3>
                  {(jobSummary?.extraction_issues ?? []).map((issue) => (
                    <p key={issue} className="warning-text">{issue}</p>
                  ))}
                  <p className="muted">See <strong>Issues &amp; Quality</strong> in the sidebar for how to fix.</p>
                </div>
              )}

              <div className="address-grid">
                <AddressCard title="Billing Address" data={doc.billing_address} />
                <AddressCard title="Receiver Billing Address" data={doc.receiver_billing_address} />
                <AddressCard title="Shipping Address" data={doc.shipping_address} />
                <AddressCard title="Receiver Shipping Address" data={doc.receiver_shipping_address} />
              </div>

              <div className="meta-grid">
                <div className="meta-card">
                  <h3>Document Details</h3>
                  <p><strong>Document title:</strong> {doc.header.document_heading || doc.document_type || '—'}</p>
                  <p><strong>Category:</strong> {doc.document_type}</p>
                  <p><strong>System Ref No:</strong> {doc.header.system_ref_no || '—'}</p>
                  <p><strong>Invoice Number:</strong> {doc.header.invoice_number || '—'}</p>
                  <p><strong>Credit Note No:</strong> {doc.header.credit_note_number || '—'}</p>
                  <p><strong>Credit Note Date:</strong> {doc.header.credit_note_date || '—'}</p>
                  <p><strong>Debit Note No:</strong> {doc.header.debit_note_number || '—'}</p>
                  <p><strong>Debit Note Date:</strong> {doc.header.debit_note_date || '—'}</p>
                  <p><strong>RMA No:</strong> {doc.header.rma_number || '—'}</p>
                  <p><strong>Return ID:</strong> {doc.header.return_id || '—'}</p>
                  <p><strong>Removal ID:</strong> {doc.header.removal_id || '—'}</p>
                  <p><strong>VRET Shipment ID:</strong> {doc.header.vret_shipment_id || '—'}</p>
                </div>
                <div className="meta-card">
                  <h3>Payment & Terms</h3>
                  <p><strong>Due Date:</strong> {doc.header.due_date || '—'}</p>
                  <p><strong>Payment Method:</strong> {doc.header.payment_method || '—'}</p>
                  <p><strong>Payment Term:</strong> {doc.header.payment_terms || '—'}</p>
                  <p><strong>Reason:</strong> {doc.header.reason || '—'}</p>
                  <p><strong>Call Tag ID:</strong> {doc.header.call_tag_id || '—'}</p>
                  <p><strong>Place of Supply:</strong> {doc.header.place_of_supply || doc.receiver_shipping_address?.place_of_supply || '—'}</p>
                </div>
                <div className="meta-card">
                  <h3>Reference & Totals</h3>
                  <p><strong>Invoice Reference:</strong> {doc.header.invoice_reference_number || '—'}</p>
                  <p><strong>Subtotal:</strong> ₹{doc.totals.subtotal ?? 0}</p>
                  <p><strong>Tax:</strong> ₹{doc.totals.tax_total ?? 0}</p>
                  <p><strong>Grand Total:</strong> ₹{doc.totals.grand_total ?? 0}</p>
                  <p><strong>Validation:</strong> <span className={`badge badge-${doc.validation.status}`}>{doc.validation.status}</span></p>
                  {doc.audit.json_path && <p className="muted"><strong>JSON:</strong> {doc.audit.json_path}</p>}
                </div>
              </div>

              {(doc.validation.warnings.length > 0 || doc.validation.errors.length > 0) && (
                <div className="panel inset-panel">
                  <h3>Validation Notes</h3>
                  {doc.validation.errors.map((e) => <p key={e} className="error-text">{e}</p>)}
                  {doc.validation.warnings.map((w) => <p key={w} className="warning-text">{w}</p>)}
                </div>
              )}
            </>
          )}

          {tab === 'line_items' && (
            doc.line_items.length === 0 ? (
              <p className="muted">No line items extracted. The document may be scanned or use a non-standard layout.</p>
            ) : (
              <div className="table-wrap wide-table">
                <table className="data-table">
                  <thead>
                    <tr>
                      {LINE_ITEM_COLUMNS.map((col) => (
                        <th key={col.key}>{col.label}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {doc.line_items.map((item, i) => (
                      <tr key={i}>
                        {LINE_ITEM_COLUMNS.map((col) => (
                          <td key={col.key} className={col.key === 'product' ? 'cell-product' : undefined}>
                            {formatCell(item[col.key])}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          )}

          {tab === 'flat' && (
            flatRows.length === 0 ? (
              <p className="muted">No flat export rows available.</p>
            ) : (
              <div className="table-wrap flat-table">
                <table className="data-table">
                  <thead>
                    <tr>
                      {flatColumns.map((col) => (
                        <th key={col.key}>{col.label}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {flatRows.map((row, i) => (
                      <tr key={i}>
                        {flatColumns.map((col) => (
                          <td key={col.key}>{formatCell(row[col.key] as string | number | undefined)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          )}

          {tab === 'raw' && (
            <div className="raw-text">
              {doc.raw_data.pages.map((page) => (
                <div key={page.page_number} className="raw-page">
                  <h3>Page {page.page_number}</h3>
                  <pre>{page.raw_text || '(empty)'}</pre>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  )
}
