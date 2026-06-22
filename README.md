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

## Docker (single image)

Build and run the full stack (API + UI) in one container:

```bash
docker build -t invoice-management:latest .
docker run --rm -p 8080:8080 -v invoice-data:/app/data invoice-management:latest
```

Open the app at <http://localhost:8080>. API docs: <http://localhost:8080/api/docs>.

Or use Docker Compose:

```bash
docker compose up --build
```

### Share the image

Export for offline use:

```bash
docker save invoice-management:latest -o invoice-management.tar
```

On another machine:

```bash
docker load -i invoice-management.tar
docker run --rm -p 8080:8080 -v invoice-data:/app/data invoice-management:latest
```

Uploaded files and extracted JSON are stored in the `invoice-data` volume at `/app/data` inside the container.

## Account team install (Docker pull only)

For people on the account team: **no GCP, no AWS, no source code** — only Docker Desktop and a pull from Docker Hub (or similar).

### What you (maintainer) do once

1. Log in to [Docker Hub](https://hub.docker.com/) (repo: `yashjeetamai/invoice-finintel`).

```bash
docker login
```

2. Build and push (replace `1.0.0` with your version tag):

```bash
docker build -t yashjeetamai/invoice-finintel:1.0.0 .
docker push yashjeetamai/invoice-finintel:1.0.0
docker tag yashjeetamai/invoice-finintel:1.0.0 yashjeetamai/invoice-finintel:latest
docker push yashjeetamai/invoice-finintel:latest
```

Or from the `deploy` folder on Windows:

```powershell
.\publish.ps1 -Tag "1.0.0"
```

3. Tell the team to use: `yashjeetamai/invoice-finintel:latest` (or a specific tag like `1.0.0`).

### What each account team person does

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and start it.
2. Run **one** of these:

**Windows (PowerShell):**

```powershell
cd deploy
.\install.ps1
```

**Mac / Linux:**

```bash
cd deploy
chmod +x install.sh
./install.sh
```

**Or manual (any OS):**

```bash
docker pull yashjeetamai/invoice-finintel:latest
docker run -d --name invoice-app -p 8080:8080 -v invoice-data:/app/data yashjeetamai/invoice-finintel:latest
```

3. Open **http://localhost:8080**

### Updates

When you publish a new version:

```bash
docker build -t yashjeetamai/invoice-finintel:latest .
docker push yashjeetamai/invoice-finintel:latest
```

Tell the team to run:

```bash
docker pull yashjeetamai/invoice-finintel:latest
docker restart invoice-app
```

Or re-run `deploy\install.ps1` / `deploy/install.sh`.

### Private image (optional)

If the image is private on Docker Hub, each person runs **once**:

```bash
docker login
```

Use a shared **read-only** access token you create in Docker Hub (not your personal password). Still no GCP or cloud console.

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
