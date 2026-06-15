"""Regression: line item split across page break (30001117227.pdf)."""
from pathlib import Path

from app.extractors import parse_document, read_document

PDF = Path(r"c:\Users\Inno\Downloads\30001117227-page changes.pdf")

EXPECTED_COUNT = 3
EXPECTED_TOTALS = [146.35, 2467.64, 1288.65]
EXPECTED_PRODUCT_SNIPPETS = [
    "Microfiber Cloth",
    "Car Inflatable Bed",
    "Polyvinyl Chloride Car Bed",
]
EXPECTED_ITEM2 = {
    "hsn": "40169590",
    "asin": "B0D9QQWDS3",
    "ean": "",
    "combo": "4EA6XFXE",
    "invoice_no": "ETD/25-26/0403",
    "invoice_date": "05-SEP-2025",
    "return_id": "149926774229552",
    "shipment_id": "546542171347001",
    "cost_per_unit": 2091.22,
    "total_cost": 2091.22,
    "tax_rate": 18.0,
    "tax_type": "IGST",
    "tax_amount": 376.42,
}


def main() -> None:
    if not PDF.exists():
        print(f"SKIP: PDF not found at {PDF}")
        return

    doc = parse_document(PDF.name, read_document(PDF))
    items = doc["line_items"]

    failures: list[str] = []
    if len(items) != EXPECTED_COUNT:
        failures.append(f"count: expected {EXPECTED_COUNT}, got {len(items)}")

    for index, (item, total, snippet) in enumerate(
        zip(items, EXPECTED_TOTALS, EXPECTED_PRODUCT_SNIPPETS, strict=False), start=1
    ):
        if abs(item.total_amount - total) > 0.01:
            failures.append(f"item {index} total: expected {total}, got {item.total_amount}")
        if snippet not in item.product:
            failures.append(f"item {index} product missing {snippet!r}: {item.product[:80]!r}")

    item2 = items[1]
    for field, expected in EXPECTED_ITEM2.items():
        got = getattr(item2, field)
        if isinstance(expected, float):
            if abs(float(got or 0) - expected) > 0.02:
                failures.append(f"item 2 {field}: expected {expected}, got {got}")
        elif got != expected:
            failures.append(f"item 2 {field}: expected {expected!r}, got {got!r}")
    if "Beach" not in item2.product:
        failures.append(f"item 2 missing page-2 description tail: {item2.product[:100]!r}")

    if failures:
        print("FAIL")
        for msg in failures:
            print(f"  - {msg}")
        raise SystemExit(1)

    print(f"PASS: {len(items)} line items, full page-break merge OK")


if __name__ == "__main__":
    main()
