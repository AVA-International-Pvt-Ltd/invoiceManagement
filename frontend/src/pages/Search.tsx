import { useState } from 'react'

type SearchResult = {
  job_id?: string
  invoice_number?: string
  vendor?: string
}

export function Search() {
  const [invoiceNumber, setInvoiceNumber] = useState('')
  const [vendor, setVendor] = useState('')
  const [gstin, setGstin] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [count, setCount] = useState(0)
  const [searched, setSearched] = useState(false)

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault()
    const params = new URLSearchParams()
    if (invoiceNumber) params.set('invoice_number', invoiceNumber)
    if (vendor) params.set('vendor', vendor)
    if (gstin) params.set('gstin', gstin)

    const res = await fetch(`/api/v1/search?${params}`)
    const data = await res.json()
    setResults(data.results ?? [])
    setCount(data.count ?? 0)
    setSearched(true)
  }

  return (
    <>
      <section className="panel">
        <h2>Search Documents</h2>
        <form className="search-form" onSubmit={handleSearch}>
          <div className="form-row">
            <label>
              Invoice Number
              <input
                type="text"
                value={invoiceNumber}
                onChange={(e) => setInvoiceNumber(e.target.value)}
                placeholder="INV-2024-001"
              />
            </label>
            <label>
              Vendor
              <input
                type="text"
                value={vendor}
                onChange={(e) => setVendor(e.target.value)}
                placeholder="Vendor name"
              />
            </label>
            <label>
              GSTIN
              <input
                type="text"
                value={gstin}
                onChange={(e) => setGstin(e.target.value)}
                placeholder="29AAAAA0000A1Z5"
              />
            </label>
          </div>
          <button type="submit" className="primary-btn">
            Search
          </button>
        </form>
      </section>

      {searched && (
        <section className="panel">
          <h2>Results ({count})</h2>
          {results.length === 0 ? (
            <p className="muted">No documents match your filters.</p>
          ) : (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Invoice</th>
                    <th>Vendor</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((r, i) => (
                    <tr key={r.job_id ?? i}>
                      <td>{r.invoice_number ?? '—'}</td>
                      <td>{r.vendor ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </>
  )
}
