"""Review all 201 PDFs after 17-box page-break merge."""
from __future__ import annotations

from pathlib import Path

from app.extractors import parse_document, read_document
from app.extractors.pagebreak import TOTAL_QTY_RE, reprint_match_key
from app.storage import UPLOAD_DIR

TOLERANCE = 0.12


def main() -> None:
    pdfs = sorted(UPLOAD_DIR.glob("*.pdf"))
    total = len(pdfs)
    ok_total = 0
    dup_sl = 0
    over_extract = 0
    under_extract = 0
    legit_same_sku_pairs = 0
    grand_mismatch = 0
    issues: list[str] = []

    for pdf in pdfs:
        pages = read_document(pdf)
        text = "\n".join(p.raw_text for p in pages)
        parsed = parse_document(pdf.name, pages)
        items = parsed.get("line_items", [])
        totals = parsed.get("totals", {})
        grand = round(float(totals.get("grand_total", 0.0)), 2)
        line_sum = round(sum(i.total_amount for i in items), 2)

        qty_match = TOTAL_QTY_RE.search(text)
        expected_qty = int(qty_match.group(1)) if qty_match else None
        actual_qty = round(sum(i.quantity for i in items), 2)

        serials = [i.system_ref_no for i in items if (i.system_ref_no or "").strip()]
        if len(serials) != len(set(serials)):
            dup_sl += 1
            issues.append(f"DUPLICATE SL: {pdf.name}")

        if expected_qty is not None and actual_qty > expected_qty + 0.01:
            over_extract += 1
            issues.append(f"QTY OVER: {pdf.name} expected={expected_qty} got={actual_qty}")
        elif expected_qty is not None and actual_qty < expected_qty - 0.01:
            under_extract += 1

        if grand and abs(line_sum - grand) > TOLERANCE:
            grand_mismatch += 1
            issues.append(f"GRAND TOTAL: {pdf.name} lines={line_sum} grand={grand}")

        for i in range(len(items) - 1):
            a, b = items[i], items[i + 1]
            if (
                a.asin
                and a.asin == b.asin
                and abs(a.total_amount - b.total_amount) < 0.02
                and a.system_ref_no
                and b.system_ref_no
                and a.system_ref_no != b.system_ref_no
            ):
                legit_same_sku_pairs += 1

        if abs(line_sum - grand) <= TOLERANCE and not (
            expected_qty is not None and actual_qty > expected_qty + 0.01
        ):
            ok_total += 1

    print(f"Reviewed: {total} PDFs")
    print(f"Grand total OK (±{TOLERANCE}): {total - grand_mismatch}/{total}")
    print(f"Duplicate Sl. No. in export: {dup_sl} (should be 0)")
    print(f"Total Qty sum over-extracted: {over_extract}")
    print(f"Total Qty sum under-extracted: {under_extract}")
    print(f"Legit same-SKU pairs (different Sl. No. kept): {legit_same_sku_pairs}")
    print(f"Fully clean (total + no over-qty): {ok_total}/{total}")
    if issues:
        print("\nIssues (first 20):")
        for line in issues[:20]:
            print(" ", line)


if __name__ == "__main__":
    main()
