# Enterprise Financial Document Intelligence Platform

This repository contains a production-oriented foundation for a financial document intelligence SaaS platform that ingests invoices, credit notes, debit notes, R4C documents, settlement reports, GST documents, and related financial records.

## What This Initial Version Includes

- Modular backend skeleton (FastAPI)
- End-to-end pipeline contract (classification -> OCR/layout -> extraction -> validation -> normalization)
- Canonical normalized JSON schema with raw-preservation model
- Processing/job APIs to submit documents and track status
- Architecture and scale blueprint for enterprise deployment

## Planned Modules

1. Upload Engine
2. Document Processing Pipeline
3. OCR/Layout Engine
4. Classification Engine
5. Extraction and Line-Item Engine
6. Validation and Reconciliation Engine
7. Search and Analytics
8. Excel Export Engine
9. Enterprise Viewer
10. RBAC + Audit + Observability

## Quick Start

### 1) Create Python environment

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r backend/requirements.txt
```

### 2) Run API

```bash
uvicorn app.main:app --reload --app-dir backend
```

### 3) Open docs

Swagger: <http://127.0.0.1:8000/docs>

## Repository Structure

```text
backend/
  app/
    main.py
    models.py
    pipeline.py
data/
  uploads/          # original uploaded files
  extractions/      # one normalized JSON file per document
  index.json        # lightweight document index
schemas/
  normalized-document.schema.json
docs/
  architecture.md
```

## Local JSON Storage

All extracted data is saved locally in this project as JSON only (no database).

- Each upload creates: `data/extractions/{job_id}.json`
- Document index: `data/index.json`
- Original files: `data/uploads/`

Each extraction JSON includes the full normalized document (header, vendor, line items, tax, validation, raw OCR text).

## Notes

- This baseline preserves all extracted/raw data by design.
- OCR and model providers are intentionally abstracted so you can plug in AWS Textract, Google Document AI, Azure Form Recognizer, Tesseract, PaddleOCR, or hybrid pipelines.
- The schema is designed to retain 100% source information while providing business-ready normalized output.
