"""Deep audit of all stored extractions — totals, qty, page-breaks, ETRADE headers."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from app.extraction_quality import assess_document
from app.job_summary import detect_document_subtype, detect_source
from app.models import NormalizedDocument
from app.storage import EXTRACTIONS_DIR

ASIN_RE = re.compile(r"^B0[A-Z0-9]{8}$", re.I)
TOTAL_QTY_RE = re.compile(r"Total Qty:\s*(\d+(?:\.\d+)?)", re.I)
PAGE_RE = re.compile(r"Page\s+(\d+)\s+of\s+(\d+)", re.I)


def hsn_digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def item_key(item) -> str:
    return "|".join(
        [
            item.system_ref_no,
            item.product[:60],
            item.asin,
            item.ean,
            str(item.quantity),
            str(item.total_amount),
        ]
    )


def main() -> None:
    issues: list[dict] = []
    pagebreak_suspects: list[dict] = []
    field_gaps: list[dict] = []
    stats = {"total": 0, "multi_page": 0, "verified": 0, "failed_qa": 0}

    for path in sorted(EXTRACTIONS_DIR.glob("*.json")):
        stats["total"] += 1
        stored = json.loads(path.read_text(encoding="utf-8-sig"))
        doc = NormalizedDocument.model_validate(stored["document"])
        file_name = doc.audit.get("file_name", path.stem)
        header = doc.header or {}
        items = doc.line_items
        text = "\n".join(p.get("raw_text", "") for p in (doc.raw_data or {}).get("pages", []))

        qa = assess_document(doc)
        if qa["extraction_status"] != "verified":
            stats["failed_qa"] += 1
            issues.append({"file": file_name, "type": "qa_fail", "issues": qa["extraction_issues"]})
        else:
            stats["verified"] += 1

        pages_match = PAGE_RE.search(text)
        page_count = int(pages_match.group(2)) if pages_match else 1
        if page_count > 1:
            stats["multi_page"] += 1

        source = detect_source(doc.vendor.name, doc.vendor.gstin, doc.vendor.pan)
        subtype = detect_document_subtype(doc.document_type.value, header.get("reason", ""), file_name)

        if source == "etrade":
            gaps: list[str] = []
            if not header.get("system_ref_no"):
                gaps.append("missing system_ref_no")
            if subtype == "invoice" and not header.get("invoice_number"):
                gaps.append("missing invoice_number")
            if subtype in ("credit_note", "cancellation") and not header.get("credit_note_number"):
                gaps.append("missing credit_note_number")
            if subtype == "invoice" and not header.get("invoice_reference_number"):
                gaps.append("missing invoice_reference_number")
            if gaps:
                field_gaps.append({"file": file_name, "subtype": subtype, "gaps": gaps})

        for idx, item in enumerate(items):
            asin = (item.asin or "").strip()
            hsn = hsn_digits(item.hsn)

            if asin and asin.startswith("B0") and not ASIN_RE.match(asin):
                pagebreak_suspects.append(
                    {
                        "file": file_name,
                        "item": idx + 1,
                        "issue": "partial ASIN (page-break split?)",
                        "value": asin,
                        "product": item.product[:60],
                    }
                )
            if item.hsn and 0 < len(hsn) < 6:
                pagebreak_suspects.append(
                    {
                        "file": file_name,
                        "item": idx + 1,
                        "issue": "partial HSN (page-break split?)",
                        "value": item.hsn,
                        "product": item.product[:60],
                    }
                )
            if item.quantity > 10_000:
                pagebreak_suspects.append(
                    {
                        "file": file_name,
                        "item": idx + 1,
                        "issue": "corrupted quantity",
                        "value": item.quantity,
                    }
                )

        for i in range(1, len(items)):
            prev, cur = items[i - 1], items[i]
            prev_page = (prev.source_ref.page if prev.source_ref else 0) or 0
            cur_page = (cur.source_ref.page if cur.source_ref else 0) or 0
            if cur_page > prev_page and not (cur.system_ref_no or "").strip():
                if cur.product.strip() or (cur.asin and not ASIN_RE.match(cur.asin)):
                    pagebreak_suspects.append(
                        {
                            "file": file_name,
                            "item": i + 1,
                            "issue": "possible unmerged page-2 tail row",
                            "product": cur.product[:60],
                            "asin": cur.asin,
                        }
                    )
            if item_key(prev) == item_key(cur):
                pagebreak_suspects.append(
                    {
                        "file": file_name,
                        "item": i + 1,
                        "issue": "duplicate line item",
                    }
                )

        qty_match = TOTAL_QTY_RE.search(text)
        if qty_match and items:
            expected_qty = float(qty_match.group(1))
            got_qty = sum(float(i.quantity or 0) for i in items)
            if abs(expected_qty - got_qty) > 0.01:
                issues.append(
                    {
                        "file": file_name,
                        "type": "qty_mismatch",
                        "expected": expected_qty,
                        "got": got_qty,
                        "items": len(items),
                    }
                )

        grand = float((doc.totals or {}).get("grand_total") or 0)
        line_sum = round(sum(float(i.total_amount or 0) for i in items), 2)
        if items and grand and abs(line_sum - grand) > 0.05:
            issues.append(
                {
                    "file": file_name,
                    "type": "total_mismatch",
                    "grand": grand,
                    "line_sum": line_sum,
                }
            )

    bad_files: set[str] = set()
    for row in field_gaps:
        bad_files.add(row["file"])
    for row in pagebreak_suspects:
        bad_files.add(row["file"])
    for row in issues:
        bad_files.add(row["file"])

    print("=" * 72)
    print("DEEP AUDIT REPORT — ALL STORED DOCUMENTS")
    print("=" * 72)
    print(f"Total documents:              {stats['total']}")
    print(f"Basic QA verified:              {stats['verified']}")
    print(f"Basic QA failed:                {stats['failed_qa']}")
    print(f"Multi-page PDFs:                {stats['multi_page']}")
    print(f"ETRADE header field gaps:       {len(field_gaps)}")
    print(f"Page-break / item data flags:   {len(pagebreak_suspects)}")
    print(f"Total / qty mismatches:         {len(issues)}")
    print(f"Documents with ANY flag:        {len(bad_files)} / {stats['total']}")
    print("=" * 72)

    if field_gaps:
        print("\n--- ETRADE HEADER FIELD GAPS ---")
        for row in field_gaps:
            print(f"  {row['file']}: {', '.join(row['gaps'])}")

    if pagebreak_suspects:
        print("\n--- PAGE-BREAK / LINE-ITEM SUSPECTS ---")
        by_file: dict[str, list[dict]] = defaultdict(list)
        for row in pagebreak_suspects:
            by_file[row["file"]].append(row)
        for file_name in sorted(by_file):
            rows = by_file[file_name]
            print(f"\n  {file_name} ({len(rows)} flag(s)):")
            for row in rows:
                extra = row.get("value") or row.get("asin") or row.get("product") or ""
                print(f"    - item {row['item']}: {row['issue']} {extra!r}")

    if issues:
        print("\n--- TOTAL / QTY / QA FAILURES ---")
        for row in issues:
            print(f"  {row}")

    if not bad_files:
        print("\n✓ No deep-audit issues found across all documents.")
    else:
        print(f"\n✕ {len(bad_files)} document(s) flagged — review list above.")

    # Write machine-readable report
    report_path = Path(__file__).resolve().parent.parent / "data" / "deep_audit_report.json"
    report_path.write_text(
        json.dumps(
            {
                "stats": stats,
                "field_gaps": field_gaps,
                "pagebreak_suspects": pagebreak_suspects,
                "issues": issues,
                "flagged_files": sorted(bad_files),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nFull report saved: {report_path}")


if __name__ == "__main__":
    main()
