from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
EXTRACTIONS_DIR = DATA_DIR / "extractions"
INDEX_FILE = DATA_DIR / "index.json"


def ensure_dirs() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    EXTRACTIONS_DIR.mkdir(parents=True, exist_ok=True)


def save_upload(filename: str, content: bytes) -> Path:
    ensure_dirs()
    safe_name = filename.replace("\\", "_").replace("/", "_")
    path = UPLOAD_DIR / safe_name
    if path.exists():
        stem = path.stem
        suffix = path.suffix
        counter = 1
        while path.exists():
            path = UPLOAD_DIR / f"{stem}_{counter}{suffix}"
            counter += 1
    path.write_bytes(content)
    return path


def extraction_path(job_id: str) -> Path:
    return EXTRACTIONS_DIR / f"{job_id}.json"


def save_extraction(job_id: str, payload: dict[str, Any]) -> Path:
    ensure_dirs()
    path = extraction_path(job_id)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8-sig",
    )
    _update_index(job_id, payload)
    return path


def load_extraction(job_id: str) -> dict[str, Any] | None:
    path = extraction_path(job_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_all_extractions() -> dict[str, Any]:
    ensure_dirs()
    jobs: dict[str, Any] = {}
    for path in sorted(EXTRACTIONS_DIR.glob("*.json"), reverse=True):
        jobs[path.stem] = json.loads(path.read_text(encoding="utf-8-sig"))
    return jobs


def build_extraction_payload(job_id: str, job: dict[str, Any]) -> dict[str, Any]:
    document = job.get("document") or {}
    audit = document.get("audit", {})
    audit["job_id"] = job_id
    audit["saved_at"] = datetime.now(timezone.utc).isoformat()
    audit["json_path"] = str(extraction_path(job_id).relative_to(PROJECT_ROOT)).replace("\\", "/")
    document["audit"] = audit

    return {
        "job_id": job_id,
        "status": job.get("status", "completed"),
        "saved_at": audit["saved_at"],
        "json_path": audit["json_path"],
        "document": document,
    }


def _update_index(job_id: str, payload: dict[str, Any]) -> None:
    ensure_dirs()
    index = {"jobs": [], "count": 0}
    if INDEX_FILE.exists():
        index = json.loads(INDEX_FILE.read_text(encoding="utf-8-sig"))

    document = payload.get("document") or {}
    header = document.get("header") or {}
    vendor = document.get("vendor") or {}
    totals = document.get("totals") or {}
    line_items = document.get("line_items") or []

    summary = {
        "job_id": job_id,
        "status": payload.get("status", "completed"),
        "saved_at": payload.get("saved_at"),
        "json_path": payload.get("json_path"),
        "file_name": document.get("audit", {}).get("file_name", ""),
        "document_type": document.get("document_type", "unknown"),
        "invoice_number": header.get("invoice_number") or header.get("document_number") or "",
        "vendor": vendor.get("name") or vendor.get("gstin") or "",
        "line_item_count": len(line_items),
        "grand_total": totals.get("grand_total", 0),
    }

    jobs = [item for item in index.get("jobs", []) if item.get("job_id") != job_id]
    jobs.insert(0, summary)
    index_payload = {"jobs": jobs, "count": len(jobs)}
    INDEX_FILE.write_text(
        json.dumps(index_payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8-sig",
    )


def load_index() -> dict[str, Any]:
    ensure_dirs()
    if not INDEX_FILE.exists():
        return {"jobs": [], "count": 0}
    return json.loads(INDEX_FILE.read_text(encoding="utf-8-sig"))


def _remove_from_index(job_id: str) -> None:
    ensure_dirs()
    if not INDEX_FILE.exists():
        return
    index = json.loads(INDEX_FILE.read_text(encoding="utf-8-sig"))
    jobs = [item for item in index.get("jobs", []) if item.get("job_id") != job_id]
    INDEX_FILE.write_text(
        json.dumps({"jobs": jobs, "count": len(jobs)}, indent=2, ensure_ascii=False),
        encoding="utf-8-sig",
    )


def _delete_uploaded_file(source_uri: str) -> None:
    if not source_uri:
        return
    source_path = Path(source_uri)
    if not source_path.exists():
        return
    try:
        source_path.resolve().relative_to(UPLOAD_DIR.resolve())
    except ValueError:
        return
    source_path.unlink(missing_ok=True)


def delete_document(job_id: str) -> bool:
    ensure_dirs()
    payload = load_extraction(job_id)
    deleted = False

    if payload:
        document = payload.get("document") or {}
        audit = document.get("audit") or {}
        _delete_uploaded_file(audit.get("source_uri", ""))

        json_file = extraction_path(job_id)
        if json_file.exists():
            json_file.unlink()
            deleted = True

        _remove_from_index(job_id)
        return True

    json_file = extraction_path(job_id)
    if json_file.exists():
        json_file.unlink()
        _remove_from_index(job_id)
        return True

    return deleted
