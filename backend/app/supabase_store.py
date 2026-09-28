from __future__ import annotations

import logging
import mimetypes
from typing import Any

from .config import INVOICE_BUCKET, supabase_enabled, supabase_service_role_key, supabase_url

_CLIENT: Any = None


class SupabaseStoreError(RuntimeError):
    pass


def get_client() -> Any:
    global _CLIENT
    if not supabase_enabled():
        raise SupabaseStoreError("Supabase is not configured.")
    if _CLIENT is None:
        from supabase import create_client

        _CLIENT = create_client(supabase_url(), supabase_service_role_key())
    return _CLIENT


def _safe_filename(filename: str) -> str:
    cleaned = filename.replace("\\", "_").replace("/", "_").strip()
    safe = "".join(ch if ch.isalnum() or ch in "._- " else "_" for ch in cleaned)
    return safe or "document"


def _content_type(filename: str) -> str:
    guessed, _encoding = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def upload_original(job_id: str, filename: str, content: bytes) -> str:
    storage_path = f"{job_id}/{_safe_filename(filename)}"
    bucket = get_client().storage.from_(INVOICE_BUCKET)
    try:
        bucket.upload(
            path=storage_path,
            file=content,
            file_options={"content-type": _content_type(filename), "upsert": "true"},
        )
    except Exception as exc:
        raise SupabaseStoreError(f"Could not store the file in Supabase: {exc}") from exc
    return storage_path


def _document_row(
    job_id: str,
    payload: dict[str, Any],
    *,
    uploaded_by: str | None,
) -> dict[str, Any]:
    document = payload.get("document") or {}
    header = document.get("header") or {}
    vendor = document.get("vendor") or {}
    customer = document.get("customer") or {}
    totals = document.get("totals") or {}
    audit = document.get("audit") or {}
    line_items = document.get("line_items") or []
    grand_total = totals.get("grand_total")

    return {
        "id": job_id,
        "uploaded_by": uploaded_by,
        "file_name": audit.get("file_name") or "",
        "storage_bucket": audit.get("storage_bucket") or INVOICE_BUCKET,
        "storage_path": audit.get("storage_path") or "",
        "content_hash": audit.get("content_hash") or "",
        "status": payload.get("status") or "completed",
        "document_type": document.get("document_type") or "unknown",
        "invoice_number": header.get("invoice_number") or header.get("document_number") or "",
        "vendor_name": vendor.get("name") or "",
        "vendor_gstin": vendor.get("gstin") or "",
        "customer_name": customer.get("name") or "",
        "grand_total": grand_total if isinstance(grand_total, (int, float)) else None,
        "line_item_count": len(line_items),
        "document_date": header.get("invoice_date") or header.get("document_date") or "",
        "extraction": payload,
    }


def upsert_document(
    job_id: str,
    payload: dict[str, Any],
    *,
    uploaded_by: str | None = None,
) -> None:
    client = get_client()
    row = _document_row(job_id, payload, uploaded_by=uploaded_by)
    try:
        client.table("documents").upsert(row, on_conflict="id").execute()
    except Exception as exc:
        raise SupabaseStoreError(f"Could not save extracted data: {exc}") from exc

    document = payload.get("document") or {}
    line_items = document.get("line_items") or []
    try:
        client.table("document_line_items").delete().eq("document_id", job_id).execute()
        if line_items:
            rows = [
                {"document_id": job_id, "line_index": index, "item": item}
                for index, item in enumerate(line_items)
            ]
            for start in range(0, len(rows), 500):
                client.table("document_line_items").insert(rows[start : start + 500]).execute()
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "Document %s was saved, but line items were not stored separately: %s",
            job_id,
            exc,
        )


def load_all_documents() -> dict[str, Any]:
    client = get_client()
    jobs: dict[str, Any] = {}
    start = 0
    page_size = 1000
    try:
        while True:
            response = (
                client.table("documents")
                .select("id,extraction")
                .order("created_at", desc=True)
                .range(start, start + page_size - 1)
                .execute()
            )
            batch = response.data or []
            for row in batch:
                extraction = row.get("extraction") or {}
                job_id = str(row.get("id") or extraction.get("job_id") or "")
                if job_id:
                    jobs[job_id] = extraction
            if len(batch) < page_size:
                break
            start += page_size
    except Exception as exc:
        raise SupabaseStoreError(f"Could not load documents from Supabase: {exc}") from exc
    return jobs


def load_document(job_id: str) -> dict[str, Any] | None:
    try:
        response = get_client().table("documents").select("extraction").eq("id", job_id).limit(1).execute()
    except Exception as exc:
        raise SupabaseStoreError(f"Could not load document {job_id}: {exc}") from exc
    rows = response.data or []
    if not rows:
        return None
    return rows[0].get("extraction")


def delete_document_remote(job_id: str) -> None:
    client = get_client()
    storage_path = ""
    try:
        existing = (
            client.table("documents")
            .select("storage_path")
            .eq("id", job_id)
            .limit(1)
            .execute()
        )
        rows = existing.data or []
        if rows:
            storage_path = rows[0].get("storage_path") or ""
        if storage_path:
            client.storage.from_(INVOICE_BUCKET).remove([storage_path])
        client.table("documents").delete().eq("id", job_id).execute()
    except Exception as exc:
        raise SupabaseStoreError(f"Could not delete document {job_id}: {exc}") from exc
