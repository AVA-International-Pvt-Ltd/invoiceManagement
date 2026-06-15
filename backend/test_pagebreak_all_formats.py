"""Page-break regression across all 8 document formats."""
from pathlib import Path

from app.extractors import parse_document, read_document

CASES = [
    {
        "format": "Clicktech R4C",
        "pdf": Path(r"c:\Users\Inno\Downloads\OK_26400352104832.pdf"),
        "min_items": 15,
        "max_items": 15,
    },
    {
        "format": "Clicktech GST Invoice",
        "pdf": Path(r"c:\Users\Inno\Downloads\GST Formmate.pdf"),
        "min_items": 29,
        "max_items": 29,
    },
    {
        "format": "Clicktech GST Credit Note",
        "pdf": Path(r"c:\Users\Inno\Downloads\GST Credit Note\GST Credit Note\27421653100006.pdf"),
        "min_items": 4,
        "max_items": 4,
    },
    {
        "format": "Clicktech Cancellation",
        "pdf": Path(
            r"c:\Users\Inno\Downloads\Cancellation Request for Credit\Cancellation Request for Credit\OK_26878753101442.pdf"
        ),
        "min_items": 4,
        "max_items": 4,
        "product_snippet": "Smart Screens Wall Stand",
    },
    {
        "format": "ETRADE GST Invoice",
        "pdf": Path(r"c:\Users\Inno\Downloads\GST Invoice (2)\GST Invoice\30000877790.pdf"),
        "min_items": 2,
        "max_items": 2,
    },
    {
        "format": "ETRADE GST Invoice (page break)",
        "pdf": Path(r"c:\Users\Inno\Downloads\30001117227-page changes.pdf"),
        "min_items": 3,
        "max_items": 3,
        "product_snippet": "Car Inflatable Bed",
    },
    {
        "format": "ETRADE Cancellation",
        "pdf": Path(
            r"c:\Users\Inno\Downloads\Cancellation Request for Credit\Cancellation Request for Credit\33000009259.pdf"
        ),
        "min_items": 3,
        "max_items": 3,
    },
    {
        "format": "ETRADE R4C",
        "pdf": Path(r"c:\Users\Inno\Downloads\Request for Credit (1)\Request for Credit\31000196092.pdf"),
        "min_items": 1,
        "max_items": 1,
    },
    {
        "format": "ETRADE Cancellation (Shipment ID)",
        "pdf": Path(
            r"c:\Users\Inno\Downloads\Cancellation for Credit requst\Cancellation for Credit requst\33000009506.pdf"
        ),
        "min_items": 1,
        "max_items": 1,
    },
]


def main() -> None:
    failures: list[str] = []
    for case in CASES:
        pdf = case["pdf"]
        label = case["format"]
        if not pdf.exists():
            failures.append(f"{label}: missing PDF {pdf}")
            continue

        doc = parse_document(pdf.name, read_document(pdf))
        items = doc["line_items"]
        count = len(items)
        bad_qty = [i for i in items if i.quantity > 10_000]

        if not (case["min_items"] <= count <= case["max_items"]):
            failures.append(f"{label}: expected {case['min_items']}-{case['max_items']} items, got {count}")
        if bad_qty:
            failures.append(f"{label}: {len(bad_qty)} row(s) with corrupted qty (page-break split)")

        keys = [
            "|".join(
                [
                    i.system_ref_no,
                    i.product,
                    i.sku,
                    i.hsn,
                    i.asin,
                    i.ean,
                    i.combo,
                    i.invoice_no,
                    i.invoice_date,
                    str(i.quantity),
                    str(i.total_amount),
                ]
            )
            for i in items
        ]
        if len(keys) != len(set(keys)):
            failures.append(f"{label}: duplicate line items after page-break merge")

        grand = round(float(doc.get("totals", {}).get("grand_total") or 0), 2)
        if grand > 0:
            line_sum = round(sum(float(i.total_amount or 0) for i in items), 2)
            if abs(line_sum - grand) > 0.05:
                failures.append(f"{label}: line sum {line_sum} != grand total {grand}")

        snippet = case.get("product_snippet")
        if snippet and not any(snippet in i.product for i in items):
            failures.append(f"{label}: merged product missing {snippet!r}")

        print(f"PASS {label}: items={count}")

    if failures:
        print("\nFAILURES:")
        for msg in failures:
            print(f"  - {msg}")
        raise SystemExit(1)

    print(f"\nALL {len(CASES)} page-break checks passed")


if __name__ == "__main__":
    main()
