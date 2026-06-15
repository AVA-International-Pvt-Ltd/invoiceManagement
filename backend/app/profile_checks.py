"""Detect when a PDF does not match known Clicktech / ETRADE invoice layouts."""
from __future__ import annotations

import re
from typing import Any

from .models import NormalizedDocument

ASIN_RE = re.compile(r"^B0[A-Z0-9]{8}$", re.I)
VENDOR_INVOICE_RE = re.compile(
    r"^(?:ETD/DF/\d{2}-\d{2}/\d+|(?:ETD|CKD|CTDF)/\d{2}-\d{2}/\d+)$",
    re.I,
)


def assess_profile(document: NormalizedDocument | None) -> dict[str, Any]:
    """Return layout/profile alerts — warnings only, never block saving the file."""
    from .job_summary import detect_source

    if not document:
        return {"profile_matched": False, "profile_alerts": ["Document could not be read"]}

    alerts: list[str] = []
    vendor = document.vendor
    source = detect_source(vendor.name, vendor.gstin, vendor.pan)
    if source == "unknown":
        alerts.append(
            "Layout alert: vendor is not Clicktech or ETRADE — this may be a new document template"
        )

    for idx, item in enumerate(document.line_items, 1):
        inv = (item.invoice_no or "").strip()
        if inv and not VENDOR_INVOICE_RE.match(inv):
            alerts.append(
                f"Layout alert: line {idx} vendor invoice looks incomplete ({inv}) — possible new layout"
            )
            break

        asin = (item.asin or "").strip().upper()
        if asin and asin.startswith("B0") and not ASIN_RE.match(asin):
            alerts.append(
                f"Layout alert: line {idx} ASIN may be split across pages ({asin})"
            )
            break

    return {
        "profile_matched": len(alerts) == 0,
        "profile_alerts": alerts,
    }
