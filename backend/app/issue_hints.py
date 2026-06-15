"""Human-readable fix guidance for extraction quality issues."""
from __future__ import annotations

from typing import Any

FIX_RULES: list[tuple[str, str]] = [
    (
        "no line items",
        "Upload a native PDF (not a screenshot). For scanned PDFs or images, install Tesseract OCR on the server and re-upload.",
    ),
    (
        "corrupted quantity",
        "A table row may be split across pages. Re-upload the file — the system merges page-break rows automatically. If it persists, report the invoice number.",
    ),
    (
        "line totals",
        "Totals do not match line items — often caused by a page break or missing row. Re-upload; check the Issues page for this file.",
    ),
    (
        "quantity sum",
        "Extracted quantities do not match the PDF footer. Re-upload or verify the PDF is complete (all pages included).",
    ),
    (
        "document title",
        "The PDF header was not recognized. Ensure the file is a Clicktech or ETRADE GST invoice/credit note/R4C in standard format.",
    ),
    (
        "layout alert",
        "This file may use a new or non-standard PDF layout. It is saved in the system — open it in Documents, compare with the PDF, and report the file name if values look wrong.",
    ),
    (
        "no extractable text",
        "This is likely a scanned image PDF. Install Tesseract OCR on the server, or upload a text-based (native) PDF.",
    ),
    (
        "vendor gstin",
        "Vendor GSTIN missing from header. Check that the PDF is not cropped and includes the full invoice header.",
    ),
    (
        "invoice number",
        "Document number not found. Re-upload the complete PDF or enter the number manually in your export.",
    ),
    (
        "tax mismatch",
        "Tax breakdown differs from line items. Review line items in Documents; minor rounding differences may be acceptable.",
    ),
    (
        "mismatch",
        "Some numeric fields disagree. Open the document detail, compare with the PDF, and re-upload if values are clearly wrong.",
    ),
]

DEFAULT_FIX = (
    "Open this document in Documents, compare extracted values with the PDF, "
    "and re-upload a clearer copy if needed. Contact support with the file name if the problem continues."
)


def how_to_fix(issue: str) -> str:
    lower = (issue or "").lower()
    for needle, hint in FIX_RULES:
        if needle in lower:
            return hint
    return DEFAULT_FIX


def enrich_issues(issues: list[str]) -> list[dict[str, str]]:
    return [{"issue": issue, "how_to_fix": how_to_fix(issue)} for issue in issues]
