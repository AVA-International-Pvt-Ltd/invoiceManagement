from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .auth import OrgAuthError, verify_org_user
from .config import INVOICE_BUCKET, supabase_enabled
from .duplicates import content_hash, find_prior_upload, scan_duplicates
from .export import EXPORT_COLUMNS, build_xlsx, flatten_document, flatten_jobs
from .extraction_quality import scan_all_documents
from .job_summary import build_job_summary
from .models import ExportSelectedRequest, JobResult, NormalizedDocument, ProcessRequest, ProcessResponse
from .pipeline import DocumentPipeline
from .storage import (
    build_extraction_payload,
    delete_document,
    load_all_extractions,
    load_extraction,
    save_extraction,
    save_upload,
)
from .supabase_store import (
    SupabaseStoreError,
    delete_document_remote,
    load_all_documents,
    load_document,
    upload_original,
    upsert_document,
)

api = FastAPI(title="Financial Document Intelligence API", version="0.1.0")
_cors_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
]
_cors_origins.extend(
    origin.strip()
    for origin in os.environ.get("CORS_ORIGINS", "").split(",")
    if origin.strip()
)
api.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=r"https://([a-zA-Z0-9-]+\.)?vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
pipeline = DocumentPipeline()
_JOBS: dict[str, JobResult] = {}


def _load_stored_jobs() -> dict[str, Any]:
    if supabase_enabled():
        return load_all_documents()
    return load_all_extractions()


def _load_stored_job(job_id: str) -> dict[str, Any] | None:
    if supabase_enabled():
        return load_document(job_id)
    return load_extraction(job_id)


def _hydrate_jobs() -> None:
    global _JOBS
    try:
        stored = _load_stored_jobs()
    except SupabaseStoreError as exc:
        logging.getLogger(__name__).warning("Could not load documents from Supabase: %s", exc)
        stored = {}
    for job_id, payload in stored.items():
        _JOBS[job_id] = JobResult.model_validate(payload)


def _persist_job(
    job_id: str,
    job: JobResult,
    *,
    file_bytes: bytes | None = None,
    uploaded_by: str | None = None,
) -> str:
    payload = build_extraction_payload(job_id, job.model_dump(mode="json"))
    if supabase_enabled():
        if job.document and file_bytes is not None:
            file_name = job.document.audit.get("file_name") or "document"
            storage_path = upload_original(job_id, file_name, file_bytes)
            job.document.audit["storage_bucket"] = INVOICE_BUCKET
            job.document.audit["storage_path"] = storage_path
            payload = build_extraction_payload(job_id, job.model_dump(mode="json"))
        upsert_document(job_id, payload, uploaded_by=uploaded_by)
    path = save_extraction(job_id, payload)
    if job.document:
        job.document.audit["json_path"] = payload["json_path"]
        job.document.audit["saved_at"] = payload["saved_at"]
    return str(path)


_OPEN_PATHS = {"/health", "/openapi.json", "/docs", "/redoc"}


@api.middleware("http")
async def require_org_auth(request: Request, call_next):
    if request.method == "OPTIONS" or not supabase_enabled():
        return await call_next(request)

    path = request.url.path.rstrip("/") or "/"
    if path in _OPEN_PATHS or path.startswith("/docs"):
        return await call_next(request)

    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return JSONResponse(
            {"detail": "Sign in with your @avaipl.com Google account."},
            status_code=401,
        )

    try:
        user = verify_org_user(header.split(" ", 1)[1].strip())
    except OrgAuthError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status_code)

    request.state.user_id = user["id"]
    request.state.email = user["email"]
    return await call_next(request)


_hydrate_jobs()


@api.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@api.get("/v1/quality/summary")
def quality_summary() -> dict[str, Any]:
    """Return verified / review / failed counts for all stored documents."""
    return scan_all_documents(_JOBS)


@api.get("/v1/duplicates")
def duplicates_summary() -> dict[str, Any]:
    """Return duplicate upload groups (same file content or same file name)."""
    return scan_duplicates(_JOBS)


def _build_process_response(
    job_id: str,
    job: JobResult,
    prior: dict[str, Any] | None,
) -> ProcessResponse:
    quality = build_job_summary(job_id, job)
    upload_number = (prior["upload_number"] if prior else 1)
    duplicate_message = None
    if prior:
        if prior["match_type"] == "exact":
            duplicate_message = (
                f"This exact file was uploaded before (upload #{upload_number}). "
                f"First upload: {prior['first_uploaded_at'] or 'earlier'}."
            )
        else:
            duplicate_message = (
                f"A file with the same name was uploaded before (upload #{upload_number}). "
                "Content may differ — review both copies."
            )

    return ProcessResponse(
        job_id=job_id,
        status=job.status,
        is_duplicate=bool(prior),
        duplicate_upload_number=upload_number,
        duplicate_of_job_id=prior["first_job_id"] if prior else None,
        duplicate_message=duplicate_message,
        extraction_status=quality.get("extraction_status"),
        extraction_status_label=quality.get("extraction_status_label"),
        extraction_status_symbol=quality.get("extraction_status_symbol"),
        extraction_issues=quality.get("extraction_issues") or [],
        data_quality=quality.get("data_quality"),
        profile_matched=quality.get("profile_matched", True),
        profile_alerts=quality.get("profile_alerts") or [],
    )


def _run_upload_pipeline(
    job_id: str,
    file_name: str,
    saved_path: Path,
    file_hash: str,
    file_bytes: bytes,
    uploaded_by: str | None,
) -> JobResult:
    """Extract and persist one file. Extraction errors are saved with an alert."""
    from .models import DocumentType, ValidationResult

    try:
        doc = pipeline.run(
            source_uri=str(saved_path),
            file_name=file_name,
            file_path=saved_path,
        )
        doc.audit["content_hash"] = file_hash
        job = JobResult(job_id=job_id, status="completed", document=doc)
    except Exception as exc:
        doc = NormalizedDocument(
            document_id=job_id,
            document_type=DocumentType.unknown,
            validation=ValidationResult(
                status="invalid",
                errors=[f"Extraction error: {exc}"],
            ),
            audit={
                "source_uri": str(saved_path),
                "file_name": file_name,
                "content_hash": file_hash,
            },
        )
        job = JobResult(job_id=job_id, status="completed", document=doc)

    _JOBS[job_id] = job
    try:
        _persist_job(job_id, job, file_bytes=file_bytes, uploaded_by=uploaded_by)
    except SupabaseStoreError:
        _JOBS.pop(job_id, None)
        raise
    return job


@api.post("/v1/upload", response_model=ProcessResponse)
async def upload_document(request: Request, file: UploadFile = File(...)) -> ProcessResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="filename is required")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty file")

    file_hash = content_hash(content)
    prior = find_prior_upload(_JOBS, file_hash=file_hash, file_name=file.filename)

    saved_path = save_upload(file.filename, content)
    job_id = str(uuid4())
    _JOBS[job_id] = JobResult(job_id=job_id, status="processing")

    try:
        job = _run_upload_pipeline(
            job_id,
            file.filename,
            saved_path,
            file_hash,
            content,
            getattr(request.state, "user_id", None),
        )
    except SupabaseStoreError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _build_process_response(job_id, job, prior)


@api.post("/v1/process", response_model=ProcessResponse)
def process_document(payload: ProcessRequest, request: Request) -> ProcessResponse:
    job_id = str(uuid4())
    _JOBS[job_id] = JobResult(job_id=job_id, status="processing")
    doc = pipeline.run(source_uri=payload.source_uri, file_name=payload.file_name)
    doc.audit["file_name"] = payload.file_name
    job = JobResult(job_id=job_id, status="completed", document=doc)
    _JOBS[job_id] = job
    file_bytes = None
    source = Path(payload.source_uri)
    if source.is_file():
        file_bytes = source.read_bytes()
    try:
        _persist_job(
            job_id,
            job,
            file_bytes=file_bytes,
            uploaded_by=getattr(request.state, "user_id", None),
        )
    except SupabaseStoreError as exc:
        _JOBS.pop(job_id, None)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ProcessResponse(job_id=job_id, status="completed")


@api.get("/v1/jobs")
def list_jobs() -> dict[str, Any]:
    jobs = [build_job_summary(job_id, job) for job_id, job in _JOBS.items()]
    jobs.sort(key=lambda item: item["job_id"], reverse=True)
    return {"jobs": jobs, "count": len(jobs)}


@api.get("/v1/jobs/{job_id}", response_model=JobResult)
def get_job(job_id: str) -> JobResult:
    job = _JOBS.get(job_id)
    if not job:
        stored = _load_stored_job(job_id)
        if not stored:
            raise HTTPException(status_code=404, detail="job not found")
        job = JobResult.model_validate(stored)
        _JOBS[job_id] = job
    return job


@api.get("/v1/jobs/{job_id}/json")
def get_job_json(job_id: str) -> dict[str, Any]:
    payload = _load_stored_job(job_id)
    if not payload:
        raise HTTPException(status_code=404, detail="json file not found")
    return payload


@api.get("/v1/jobs/{job_id}/export/flat")
def export_job_flat(job_id: str) -> dict[str, Any]:
    job = _JOBS.get(job_id)
    if not job:
        stored = _load_stored_job(job_id)
        if not stored:
            raise HTTPException(status_code=404, detail="job not found")
        job = JobResult.model_validate(stored)
    if not job.document:
        raise HTTPException(status_code=404, detail="document not found")
    rows = flatten_document(job_id, job.document)
    return {
        "columns": [{"key": key, "label": label} for key, label in EXPORT_COLUMNS],
        "rows": rows,
        "count": len(rows),
    }


@api.get("/v1/jobs/{job_id}/export/xlsx")
def export_job_xlsx(job_id: str) -> StreamingResponse:
    job = _JOBS.get(job_id)
    if not job:
        stored = _load_stored_job(job_id)
        if not stored:
            raise HTTPException(status_code=404, detail="job not found")
        job = JobResult.model_validate(stored)
    if not job.document:
        raise HTTPException(status_code=404, detail="document not found")

    rows = flatten_document(job_id, job.document)
    buffer = build_xlsx(rows)
    file_name = job.document.audit.get("file_name", "document").rsplit(".", 1)[0]
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{file_name}_extracted.xlsx"'},
    )


@api.get("/v1/export/xlsx")
def export_all_xlsx() -> StreamingResponse:
    jobs = [(job_id, job) for job_id, job in _JOBS.items() if job.document]
    if not jobs:
        raise HTTPException(status_code=404, detail="no documents to export")
    rows = flatten_jobs(jobs)
    buffer = build_xlsx(rows, sheet_name="All Documents")
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="all_documents_extracted.xlsx"'},
    )


@api.post("/v1/export/xlsx/selected")
def export_selected_xlsx(payload: ExportSelectedRequest) -> StreamingResponse:
    if not payload.job_ids:
        raise HTTPException(status_code=400, detail="job_ids is required")

    jobs: list[tuple[str, JobResult]] = []
    for job_id in payload.job_ids:
        job = _JOBS.get(job_id)
        if not job:
            stored = _load_stored_job(job_id)
            if not stored:
                continue
            job = JobResult.model_validate(stored)
        if job.document:
            jobs.append((job_id, job))

    if not jobs:
        raise HTTPException(status_code=404, detail="no matching documents to export")

    rows = flatten_jobs(jobs)
    buffer = build_xlsx(rows, sheet_name="Selected Documents")
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="selected_documents_extracted.xlsx"'},
    )


@api.delete("/v1/jobs/{job_id}")
def delete_job(job_id: str) -> dict[str, Any]:
    if job_id not in _JOBS and not _load_stored_job(job_id):
        raise HTTPException(status_code=404, detail="job not found")

    if supabase_enabled():
        try:
            delete_document_remote(job_id)
        except SupabaseStoreError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    delete_document(job_id)
    _JOBS.pop(job_id, None)
    return {"job_id": job_id, "status": "deleted"}


@api.get("/v1/search")
def search_documents(
    invoice_number: str | None = None,
    vendor: str | None = None,
    gstin: str | None = None,
) -> dict[str, Any]:
    results = []
    for job_id, job in _JOBS.items():
        if not job.document:
            continue
        doc = job.document
        if invoice_number:
            inv = doc.header.get("invoice_number") or doc.header.get("document_number") or ""
            if invoice_number.lower() not in inv.lower():
                continue
        if vendor:
            vendor_name = doc.vendor.name or ""
            if vendor.lower() not in vendor_name.lower():
                continue
        if gstin:
            gstin_value = doc.vendor.gstin or doc.customer.gstin or ""
            if gstin.lower() not in gstin_value.lower():
                continue
        results.append(
            {
                "job_id": job_id,
                "file_name": doc.audit.get("file_name", ""),
                "invoice_number": doc.header.get("invoice_number") or doc.header.get("document_number"),
                "vendor": doc.vendor.name or doc.vendor.gstin,
                "document_type": doc.document_type.value,
                "line_item_count": len(doc.line_items),
            }
        )
    return {
        "filters": {
            "invoice_number": invoice_number,
            "vendor": vendor,
            "gstin": gstin,
        },
        "results": results,
        "count": len(results),
    }


STATIC_DIR = os.environ.get("STATIC_DIR")
if STATIC_DIR and Path(STATIC_DIR).is_dir():
    app = FastAPI(title="Financial Document Intelligence", version="0.1.0")
    app.mount("/api", api)
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
else:
    app = api
