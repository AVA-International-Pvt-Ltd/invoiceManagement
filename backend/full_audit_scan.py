"""Comprehensive heuristic scan of all stored extractions — major + minor issues."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from app.extraction_quality import assess_document
from app.models import NormalizedDocument
from app.storage import EXTRACTIONS_DIR

ASIN_RE = re.compile(r"^B0[A-Z0-9]{8}$", re.I)
INV_RE = re.compile(r"^(?:ETD|CKD|CTDF)/[\dA-Z-]+/\d+$", re.I)
TOTAL_QTY_RE = re.compile(r"Total Qty:\s*(\d+(?:\.\d+)?)", re.I)
GRAND_TOTAL_RE = re.compile(r"Total:\s*([\d,]+(?:\.\d+)?)", re.I)


def scan() -> dict:
    major: list[dict] = []
    minor: list[dict] = []
    stats = defaultdict(int)

    for path in sorted(EXTRACTIONS_DIR.glob("*.json")):
        stored = json.loads(path.read_text(encoding="utf-8-sig"))
        doc = NormalizedDocument.model_validate(stored["document"])
        fn = doc.audit.get("file_name", path.stem)
        items = doc.line_items
        header = doc.header or {}
        totals = doc.totals or {}
        text = "\n".join(
            p.get("raw_text", "") for p in (doc.raw_data or {}).get("pages", [])
        )

        qa = assess_document(doc)
        if qa["extraction_status"] == "failed":
            major.append(
                {
                    "file": fn,
                    "category": "qa_failed",
                    "detail": "; ".join(qa["extraction_issues"]),
                }
            )
        elif qa["extraction_status"] == "needs_review":
            minor.append(
                {
                    "file": fn,
                    "category": "needs_review",
                    "detail": "; ".join(qa["extraction_issues"]),
                }
            )

        grand = float(totals.get("grand_total") or 0)
        line_sum = round(sum(float(i.total_amount or 0) for i in items), 2)
        if items and grand and abs(line_sum - grand) > 1.0:
            major.append(
                {
                    "file": fn,
                    "category": "total_mismatch",
                    "detail": f"lines={line_sum} grand={grand}",
                }
            )

        qty_match = TOTAL_QTY_RE.search(text)
        if qty_match and items:
            expected = float(qty_match.group(1))
            got = sum(float(i.quantity or 0) for i in items)
            if abs(expected - got) > 0.01:
                major.append(
                    {
                        "file": fn,
                        "category": "qty_mismatch",
                        "detail": f"pdf={expected:g} extracted={got:g}",
                    }
                )

        if not header.get("document_heading"):
            minor.append({"file": fn, "category": "missing_title", "detail": ""})

        for idx, item in enumerate(items, 1):
            inv = (item.invoice_no or "").strip()
            if inv:
                if re.search(r"\d\.\d", inv.replace(",", "")):
                    major.append(
                        {
                            "file": fn,
                            "category": "invoice_has_decimal",
                            "detail": f"item {idx}: {inv!r}",
                        }
                    )
                elif len(inv) > 22:
                    major.append(
                        {
                            "file": fn,
                            "category": "invoice_too_long",
                            "detail": f"item {idx}: {inv!r}",
                        }
                    )
                elif not INV_RE.match(inv) and inv not in {"", "-"}:
                    minor.append(
                        {
                            "file": fn,
                            "category": "invoice_format",
                            "detail": f"item {idx}: {inv!r}",
                        }
                    )

            asin = (item.asin or "").strip().upper()
            if asin and asin.startswith("B0") and not ASIN_RE.match(asin):
                major.append(
                    {
                        "file": fn,
                        "category": "partial_asin",
                        "detail": f"item {idx}: {asin!r}",
                    }
                )

            hsn_digits = re.sub(r"\D", "", item.hsn or "")
            if item.hsn and 0 < len(hsn_digits) < 6:
                major.append(
                    {
                        "file": fn,
                        "category": "partial_hsn",
                        "detail": f"item {idx}: {item.hsn!r}",
                    }
                )

            qty = float(item.quantity or 0)
            if qty > 0 and abs(qty - round(qty)) > 0.001 and qty < 100:
                minor.append(
                    {
                        "file": fn,
                        "category": "fractional_qty",
                        "detail": f"item {idx}: qty={qty}",
                    }
                )
            if qty > 10_000:
                major.append(
                    {
                        "file": fn,
                        "category": "corrupted_qty",
                        "detail": f"item {idx}: qty={qty}",
                    }
                )

        for i in range(1, len(items)):
            a, b = items[i - 1], items[i]
            if (
                a.asin == b.asin
                and a.invoice_no == b.invoice_no
                and round(a.total_amount, 2) == round(b.total_amount, 2)
                and a.product[:40] == b.product[:40]
            ):
                minor.append(
                    {
                        "file": fn,
                        "category": "duplicate_item",
                        "detail": f"items {i} and {i+1}",
                    }
                )

    for bucket in (major, minor):
        for row in bucket:
            stats[row["category"]] += 1

    return {
        "major": major,
        "minor": minor,
        "stats": dict(stats),
        "major_files": sorted({r["file"] for r in major}),
        "minor_files": sorted({r["file"] for r in minor}),
    }


def main() -> None:
    result = scan()
    major = result["major"]
    minor = result["minor"]

    print("=" * 72)
    print("FULL AUDIT SCAN — ALL DOCUMENTS (after reprocess)")
    print("=" * 72)
    print(f"Major issues:   {len(major)} flags across {len(result['major_files'])} file(s)")
    print(f"Minor issues:   {len(minor)} flags across {len(result['minor_files'])} file(s)")
    print()

    if result["stats"]:
        print("Issue breakdown:")
        for cat, count in sorted(result["stats"].items(), key=lambda x: -x[1]):
            print(f"  {cat}: {count}")
    print()

    if major:
        print("--- MAJOR ISSUES ---")
        by_file: dict[str, list[dict]] = defaultdict(list)
        for row in major:
            by_file[row["file"]].append(row)
        for fn in sorted(by_file):
            print(f"\n  {fn}:")
            for row in by_file[fn]:
                print(f"    [{row['category']}] {row['detail']}")
    else:
        print("✓ No major issues detected.")

    if minor:
        print("\n--- MINOR ISSUES (sample, max 25 files) ---")
        by_file: dict[str, list[dict]] = defaultdict(list)
        for row in minor:
            by_file[row["file"]].append(row)
        for fn in sorted(by_file)[:25]:
            print(f"\n  {fn}:")
            for row in by_file[fn][:3]:
                print(f"    [{row['category']}] {row['detail']}")
        if len(by_file) > 25:
            print(f"\n  ... and {len(by_file) - 25} more files with minor flags")

    out = Path("../data/full_audit_report.json")
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nReport saved: {out}")


if __name__ == "__main__":
    main()
