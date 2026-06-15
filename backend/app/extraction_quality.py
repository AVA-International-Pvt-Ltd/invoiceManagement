"""Assess whether extracted document data is reliable for export."""
from __future__ import annotations

import re
from typing import Any

from .issue_hints import enrich_issues
from .models import JobResult, NormalizedDocument
from .profile_checks import assess_profile
TOTAL_QTY_RE = re.compile(r"Total Qty:\s*(\d+(?:\.\d+)?)", re.I)
MAX_PLAUSIBLE_QTY = 10_000
TOTAL_TOLERANCE = 1.0

STATUS_LABELS = {
    "verified": "Verified",
    "needs_review": "Review suggested",
    "failed": "Unreliable — re-upload or enter manually",
}

STATUS_SYMBOLS = {
    "verified": "✓",
    "needs_review": "⚠",
    "failed": "✕",
}


def _document_text(document: NormalizedDocument) -> str:
    raw = document.raw_data or {}
    pages = raw.get("pages") or []
    return "\n".join(str(p.get("raw_text") or "") for p in pages)


def assess_document(document: NormalizedDocument | None) -> dict[str, Any]:
    if not document:
        return {
            "extraction_status": "failed",
            "extraction_status_label": STATUS_LABELS["failed"],
            "extraction_status_symbol": STATUS_SYMBOLS["failed"],
            "extraction_issues": ["Document not processed"],
            "extraction_issues_detailed": enrich_issues(["Document not processed"]),
            "profile_matched": False,
            "profile_alerts": ["Document not processed"],
        }

    errors: list[str] = []
    warnings: list[str] = []
    items = document.line_items
    totals = document.totals or {}
    validation = document.validation

    if not items:
        errors.append("No line items extracted")

    if any(item.quantity > MAX_PLAUSIBLE_QTY for item in items):
        errors.append("Corrupted quantity detected in line items")

    grand = float(totals.get("grand_total") or 0)
    line_sum = round(sum(float(item.total_amount or 0) for item in items), 2)
    if items and grand and abs(line_sum - grand) > TOTAL_TOLERANCE:
        errors.append(f"Line totals ({line_sum}) do not match invoice total ({grand})")

    text = _document_text(document)
    qty_match = TOTAL_QTY_RE.search(text)
    if qty_match and items:
        expected_qty = float(qty_match.group(1))
        qty_sum = sum(float(item.quantity or 0) for item in items)
        if abs(qty_sum - expected_qty) > 0.01:
            errors.append(
                f"Quantity sum ({qty_sum:g}) does not match PDF Total Qty ({expected_qty:g})"
            )

    if not (document.header or {}).get("document_heading"):
        warnings.append("Document title not detected")

    profile = assess_profile(document)
    for alert in profile.get("profile_alerts") or []:
        warnings.append(alert)

    for warning in (validation.warnings or []):
        lower = warning.lower()
        if "tax mismatch" in lower:
            # Line totals already match the invoice — tax header detail is non-critical.
            if items and grand and abs(line_sum - grand) <= TOTAL_TOLERANCE:
                continue
        if "mismatch" in lower:
            warnings.append(warning)

    for error in validation.errors or []:
        errors.append(error)

    if errors:
        status = "failed"
    elif warnings:
        status = "needs_review"
    else:
        status = "verified"

    issues = errors + warnings
    return {
        "extraction_status": status,
        "extraction_status_label": STATUS_LABELS[status],
        "extraction_status_symbol": STATUS_SYMBOLS[status],
        "extraction_issues": issues[:8],
        "extraction_issues_detailed": enrich_issues(issues),
        "profile_matched": profile.get("profile_matched", True),
        "profile_alerts": profile.get("profile_alerts") or [],
    }


def assess_job(job: JobResult) -> dict[str, Any]:
    return assess_document(job.document)


def scan_all_documents(jobs: dict[str, JobResult] | None = None) -> dict[str, Any]:
    """Scan every stored extraction and return quality totals."""
    if jobs is None:
        from .storage import load_all_extractions

        stored = load_all_extractions()
        jobs = {job_id: JobResult.model_validate(payload) for job_id, payload in stored.items()}

    total = 0
    verified = 0
    needs_review = 0
    failed = 0
    not_verified: list[dict[str, Any]] = []
    all_documents: list[dict[str, Any]] = []

    for job_id, job in jobs.items():
        if not job.document:
            continue
        total += 1
        doc = job.document
        file_name = doc.audit.get("file_name", job_id)
        quality = assess_document(doc)
        status = quality["extraction_status"]

        if status == "verified":
            verified += 1
        elif status == "needs_review":
            needs_review += 1
        else:
            failed += 1

        entry = {
            "job_id": job_id,
            "file_name": file_name,
            "status": status,
            "status_label": quality["extraction_status_label"],
            "status_symbol": quality["extraction_status_symbol"],
            "issues": quality["extraction_issues"],
            "issues_detailed": quality["extraction_issues_detailed"],
            "uploaded_at": doc.audit.get("saved_at") or "",
            "profile_matched": quality.get("profile_matched", True),
            "profile_alerts": quality.get("profile_alerts") or [],
        }
        all_documents.append(entry)
        if status != "verified":
            not_verified.append(entry)

    verified_percent = round(100 * verified / total, 1) if total else 100.0
    layout_alert_count = sum(1 for doc in all_documents if not doc.get("profile_matched", True))
    return {
        "total": total,
        "verified": verified,
        "needs_review": needs_review,
        "failed": failed,
        "verified_percent": verified_percent,
        "all_verified": total > 0 and verified == total,
        "layout_alert_count": layout_alert_count,
        "not_verified": not_verified,
        "documents": all_documents,
    }