# Architecture Blueprint

## System Goals

- Never discard source information.
- Produce normalized, business-ready JSON.
- Support line-item level reconciliation and tax validation.
- Scale to 10M documents and 100M+ line items.

## High-Level Architecture

1. **Ingestion Layer**
   - Presigned uploads (PDF/JPG/PNG/TIFF)
   - Bulk/folder upload orchestration
   - Virus scan + checksum
   - Immutable object storage

2. **Processing Orchestration**
   - Queue-based async jobs
   - Idempotent processing keys
   - Retry + dead-letter queues
   - Versioned extraction pipeline

3. **Document Intelligence Pipeline**
   - Document classification
   - OCR and layout extraction
   - Table detection and continuation resolution across pages
   - Header/party/entity extraction
   - Line-item extraction and enrichment
   - Validation and reconciliation
   - Normalized output generation

4. **Persistence**
   - Raw artifact store (tokens, boxes, images, tables)
   - Normalized JSON store
   - Search index (hybrid: full text + faceted)
   - Audit/event log

5. **Application Layer**
   - API for upload, process, search, export
   - Document viewer with field and line-item highlights
   - Dashboard and analytics
   - Role-based access control (RBAC)

## Recommended Runtime Stack

- **API**: FastAPI
- **Queue**: Redis Streams / Kafka / SQS
- **Worker**: Celery / Temporal / Arq
- **Storage**: S3-compatible object storage
- **Database**: PostgreSQL (OLTP) + partitioned tables
- **Search**: OpenSearch / Elasticsearch
- **Analytics**: ClickHouse / BigQuery / Snowflake
- **Frontend**: Next.js + TypeScript + TanStack Table

## Pipeline Contract

Each pipeline step accepts and emits a `ProcessingContext`:

- `document_id`
- `source_uri`
- `classification`
- `raw_pages` (full fidelity)
- `extracted_fields`
- `line_items`
- `validations`
- `normalized_document`
- `metadata` (model versions, latency, confidence)

## Multi-Page Table Intelligence

Algorithm requirements:

1. Detect candidate table regions with coordinates per page.
2. Identify repeated headers/footers by fuzzy line signatures.
3. Link table fragments by:
   - same column structure similarity
   - page continuity
   - textual continuation cues
4. Merge split rows using vertical-overlap + token adjacency.
5. Keep deterministic row sequence.
6. Emit provenance (`page`, `bbox`, `token_ids`) per merged row.

## Validation Layer

- Tax equation checks (CGST/SGST/IGST/CESS/TCS/TDS)
- Header vs line-item amount reconciliation
- Mandatory field validation (invoice no, GSTIN, date)
- Duplicate item detection
- Missing page / page-order anomalies

Each validation emits:

- `rule_id`
- `severity`
- `status`
- `expected`
- `actual`
- `evidence`

## Search and Query Model

Index both normalized + raw:

- Header fields (invoice number, GSTIN, PAN)
- Party dimensions (vendor/customer)
- Product dimensions (ASIN/SKU/EAN/HSN)
- Financial measures (tax and totals)
- Date and amount ranges

## Security and Compliance

- Encryption at rest and in transit
- Tenant isolation via row-level security + object prefix isolation
- Immutable audit trail for uploads, edits, exports
- PII-aware redaction policy for derived views

## Scaling Strategy

- Horizontal workers by page-count tier
- Async extraction fan-out per page for large PDFs
- Backpressure via queue depth controls
- Partitioned storage by tenant + month
- Hot/cold storage tiers for raw artifacts

## SLO Targets

- p95 single-page end-to-end < 5s
- p95 10-page end-to-end < 15s
- p95 100-page end-to-end < 60s
