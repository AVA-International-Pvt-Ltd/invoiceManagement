"""QA audit: scan all stored extractions for data-quality issues."""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.extractors import parse_document, read_document
from app.job_summary import build_job_summary
from app.models import JobResult
from app.storage import EXTRACTIONS_DIR

TOTAL_QTY_RE = re.compile(r"Total Qty:\s*(\d+)", re.I)
MAX_QTY = 10_000
TOTAL_TOLERANCE = 1.0


def load_job(path: Path) -> tuple[str, dict]:
    stored = json.loads(path.read_text(encoding="utf-8"))
    return path.stem, stored


def audit_stored(job_id: str, stored: dict) -> list[str]:
    issues: list[str] = []
    doc = stored.get("document") or {}
    header = doc.get("header") or {}
    items = doc.get("line_items") or []
    totals = doc.get("totals") or {}
    validation = doc.get("validation") or {}
    vendor = doc.get("vendor") or {}
    audit = doc.get("audit") or {}

    if not header.get("document_heading"):
        issues.append("missing_document_heading")
    if not vendor.get("name") and not vendor.get("gstin"):
        issues.append("missing_vendor")
    if not (header.get("document_number") or header.get("invoice_number") or header.get("credit_note_number") or header.get("debit_note_number")):
        issues.append("missing_document_number")

    grand = float(totals.get("grand_total") or 0)
    line_sum = round(sum(float(i.get("total_amount") or 0) for i in items), 2)
    if grand and abs(line_sum - grand) > TOTAL_TOLERANCE:
        issues.append(f"total_mismatch(delta={round(line_sum - grand, 2)})")

    qty_sum = sum(float(i.get("quantity") or 0) for i in items)
    bad_qty = [i for i in items if float(i.get("quantity") or 0) > MAX_QTY]
    if bad_qty:
        issues.append(f"corrupted_qty({len(bad_qty)})")

    orphans = [
        i for i in items
        if not str(i.get("system_ref_no") or "").strip() and str(i.get("product") or "").strip()
    ]
    if orphans:
        issues.append(f"orphan_rows({len(orphans)})")

    empty_products = sum(1 for i in items if not str(i.get("product") or "").strip() and float(i.get("total_amount") or 0) > 0)
    if empty_products:
        issues.append(f"empty_product_rows({empty_products})")

    if not items:
        issues.append("no_line_items")

    for w in validation.get("warnings") or []:
        if "mismatch" in w.lower():
            issues.append(f"validation:{w[:60]}")

    # Re-parse PDF when available to cross-check Total Qty
    source_uri = audit.get("source_uri")
    if source_uri and Path(source_uri).is_file():
        try:
            pages = read_document(Path(source_uri))
            text = "\n".join(p.raw_text for p in pages)
            m = TOTAL_QTY_RE.search(text)
            if m:
                expected = int(m.group(1))
                if len(items) != expected:
                    issues.append(f"item_count_vs_total_qty({len(items)}!={expected})")
        except Exception as exc:
            issues.append(f"reparse_failed:{exc}")

    job = JobResult.model_validate(stored)
    summary = build_job_summary(job_id, job)
    if summary.get("source") == "unknown":
        issues.append("unknown_source")

    return issues


def main() -> None:
    files = sorted(EXTRACTIONS_DIR.glob("*.json"))
    print(f"QA AUDIT — {len(files)} documents\n")

    issue_counts: dict[str, int] = {}
    flagged: list[tuple[str, str, list[str]]] = []

    for path in files:
        job_id, stored = load_job(path)
        file_name = (stored.get("document") or {}).get("audit", {}).get("file_name", job_id)
        issues = audit_stored(job_id, stored)
        if issues:
            flagged.append((file_name, job_id, issues))
            for issue in issues:
                key = issue.split("(")[0].split(":")[0]
                issue_counts[key] = issue_counts.get(key, 0) + 1

    clean = len(files) - len(flagged)
    print(f"Clean:   {clean} / {len(files)} ({100 * clean / len(files):.1f}%)")
    print(f"Flagged: {len(flagged)} / {len(files)} ({100 * len(flagged) / len(files):.1f}%)\n")

    if issue_counts:
        print("Issue breakdown:")
        for key, count in sorted(issue_counts.items(), key=lambda x: -x[1]):
            print(f"  {key}: {count}")

    if flagged:
        print(f"\nFirst 25 flagged documents:")
        for file_name, job_id, issues in flagged[:25]:
            print(f"  {file_name}")
            print(f"    {', '.join(issues)}")

    print("\n" + "=" * 60)
    if not flagged:
        print("RESULT: ALL DOCUMENTS PASSED AUTOMATED QA")
    else:
        print(f"RESULT: {len(flagged)} DOCUMENT(S) NEED REVIEW")


if __name__ == "__main__":
    main()
