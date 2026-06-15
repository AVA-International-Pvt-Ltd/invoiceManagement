from __future__ import annotations

from typing import Any

from .extraction_quality import assess_job
from .models import JobResult, NormalizedDocument


def _document_data_quality(job_id: str, doc: NormalizedDocument, extraction_status: str) -> str:
    if extraction_status == "verified":
        return "100%"
    from .export import flatten_document

    flat_rows = flatten_document(job_id, doc)
    if not flat_rows:
        return "0%"
    scores = []
    for row in flat_rows:
        raw = str(row.get("data_quality") or "0%").replace("%", "")
        try:
            scores.append(int(raw))
        except ValueError:
            continue
    if not scores:
        return "0%"
    return f"{round(sum(scores) / len(scores))}%"

def detect_source(vendor_name: str, vendor_gstin: str, vendor_pan: str) -> str:
    haystack = f"{vendor_name} {vendor_gstin} {vendor_pan}".lower()
    if "clicktech" in haystack or "aajcc9783e" in haystack:
        return "clicktech"
    if "etrade" in haystack or "aadcv4254h" in haystack:
        return "etrade"
    return "unknown"


def detect_document_subtype(document_type: str, reason: str, file_name: str) -> str:
    doc_type = (document_type or "unknown").lower()
    reason_l = (reason or "").lower()
    file_l = (file_name or "").lower()

    if doc_type == "invoice":
        return "invoice"
    if doc_type == "r4c":
        return "r4c"
    if doc_type == "credit_note":
        if "cancellation" in reason_l or "cancellation" in file_l:
            return "cancellation"
        return "credit_note"
    if doc_type == "debit_note":
        return "debit_note"
    return doc_type


SUBTYPE_LABELS = {
    "invoice": "GST Invoice",
    "r4c": "Request for Credit",
    "credit_note": "GST Credit Note",
    "cancellation": "Cancellation of Request for Credit",
    "debit_note": "Debit Note",
    "unknown": "Unknown",
}


SOURCE_LABELS = {
    "clicktech": "Clicktech",
    "etrade": "ETRADE",
    "unknown": "Unknown",
}


def build_job_summary(job_id: str, job: JobResult) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "job_id": job_id,
        "status": job.status,
    }
    if not job.document:
        return summary

    doc = job.document
    header = doc.header or {}
    vendor = doc.vendor
    customer = doc.customer
    file_name = doc.audit.get("file_name", "")

    source = detect_source(vendor.name, vendor.gstin, vendor.pan)
    document_type = doc.document_type.value
    reason = header.get("reason") or ""
    subtype = detect_document_subtype(document_type, reason, file_name)

    qty_sum = sum(item.quantity for item in doc.line_items)

    uploaded_at = doc.audit.get("saved_at") or ""
    quality = assess_job(job)
    content_hash = doc.audit.get("content_hash") or ""

    data_quality = _document_data_quality(job_id, doc, quality["extraction_status"])

    summary.update(
        {
            "file_name": file_name,
            "content_hash": content_hash,
            "data_quality": data_quality,
            "document_type": document_type,
            "document_subtype": subtype,
            "document_subtype_label": SUBTYPE_LABELS.get(subtype, subtype),
            "document_heading": header.get("document_heading") or SUBTYPE_LABELS.get(subtype, subtype),
            "source": source,
            "source_label": SOURCE_LABELS.get(source, source),
            **quality,
            "document_number": header.get("document_number") or header.get("invoice_number") or "",
            "document_date": header.get("document_date") or "",
            "uploaded_at": uploaded_at,
            "system_ref_no": header.get("system_ref_no") or "",
            "invoice_number": header.get("invoice_number") or "",
            "credit_note_number": header.get("credit_note_number") or "",
            "invoice_reference_number": header.get("invoice_reference_number") or "",
            "customer": customer.name or customer.gstin or "",
            "vendor": vendor.name or vendor.gstin or "",
            "line_item_count": len(doc.line_items),
            "quantity_total": qty_sum,
            "grand_total": doc.totals.get("grand_total", 0),
            "place_of_supply": header.get("place_of_supply") or "",
            "reason": reason,
            "profile_matched": quality.get("profile_matched", True),
            "profile_alerts": quality.get("profile_alerts") or [],
        }
    )
    return summary
