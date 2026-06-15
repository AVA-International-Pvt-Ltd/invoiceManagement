"""Page-break validation across all stored documents."""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.extractors import parse_document, read_document
from app.extractors.pagebreak import ASIN_RE
from app.storage import EXTRACTIONS_DIR, UPLOAD_DIR

TOTAL_QTY_RE = re.compile(r"Total Qty:\s*(\d+(?:\.\d+)?)", re.I)
PAGE_RE = re.compile(r"Page\s+(\d+)\s+of\s+(\d+)", re.I)


def item_key(item) -> str:
    return "|".join(
        [
            item.system_ref_no,
            item.product[:80],
            item.asin,
            item.ean,
            item.combo,
            item.invoice_no,
            str(item.quantity),
            str(item.total_amount),
        ]
    )


def main() -> None:
    failures: list[str] = []
    stats = {
        "total": 0,
        "partial_asin": 0,
        "partial_hsn": 0,
        "duplicate_items": 0,
        "total_mismatch": 0,
        "qty_mismatch": 0,
        "passed": 0,
    }

    for path in sorted(EXTRACTIONS_DIR.glob("*.json")):
        stats["total"] += 1
        stored = json.loads(path.read_text(encoding="utf-8"))
        file_name = stored.get("document", {}).get("audit", {}).get("file_name", "")
        upload = UPLOAD_DIR / file_name
        if not upload.exists():
            failures.append(f"{file_name}: PDF missing")
            continue

        doc = parse_document(file_name, read_document(upload))
        items = doc["line_items"]
        text = "\n".join(p.raw_text for p in read_document(upload))

        for idx, item in enumerate(items, 1):
            asin = (item.asin or "").strip()
            if asin and asin.startswith("B0") and not ASIN_RE.match(asin):
                stats["partial_asin"] += 1
                failures.append(f"{file_name}: item {idx} partial ASIN {asin!r}")
            hsn_d = re.sub(r"\D", "", item.hsn or "")
            if item.hsn and 0 < len(hsn_d) < 6:
                stats["partial_hsn"] += 1
                failures.append(f"{file_name}: item {idx} partial HSN {item.hsn!r}")

        keys = [item_key(i) for i in items]
        if len(keys) != len(set(keys)):
            stats["duplicate_items"] += 1
            failures.append(f"{file_name}: duplicate line items")

        grand = round(float(doc.get("totals", {}).get("grand_total") or 0), 2)
        if items and grand:
            line_sum = round(sum(float(i.total_amount or 0) for i in items), 2)
            if abs(line_sum - grand) > 0.05:
                stats["total_mismatch"] += 1
                failures.append(f"{file_name}: line sum {line_sum} != grand {grand}")

        qty_match = TOTAL_QTY_RE.search(text)
        if qty_match and items:
            expected_qty = float(qty_match.group(1))
            got_qty = sum(float(i.quantity or 0) for i in items)
            if abs(expected_qty - got_qty) > 0.01:
                stats["qty_mismatch"] += 1
                failures.append(
                    f"{file_name}: Total Qty {expected_qty} != line qty sum {got_qty}"
                )

        if not any(f.startswith(file_name) for f in failures):
            stats["passed"] += 1

    print("=" * 72)
    print("PAGE-BREAK VALIDATION — ALL DOCUMENTS")
    print("=" * 72)
    print(f"Documents scanned:     {stats['total']}")
    print(f"Fully passed:          {stats['passed']}")
    print(f"Partial ASIN flags:    {stats['partial_asin']}")
    print(f"Partial HSN flags:     {stats['partial_hsn']}")
    print(f"Duplicate item flags:  {stats['duplicate_items']}")
    print(f"Grand total mismatch:  {stats['total_mismatch']}")
    print(f"Total Qty mismatch:    {stats['qty_mismatch']}")
    print(f"Total failure lines:   {len(failures)}")
    print("=" * 72)

    if failures:
        print("\nFAILURES (first 40):")
        for msg in failures[:40]:
            print(f"  - {msg}")
        if len(failures) > 40:
            print(f"  ... and {len(failures) - 40} more")
        raise SystemExit(1)

    print("\nAll page-break validation checks passed.")


if __name__ == "__main__":
    main()
