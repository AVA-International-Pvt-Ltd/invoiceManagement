"""Quick harness to verify parser fixes against the real PDF.

Run:  python test_extraction.py
"""
from pathlib import Path

from app.extractors import parse_document, read_document

PDF = Path(r"c:\Users\Inno\Downloads\OK_26400352104832.pdf")

EXPECTED_QTY = 176
EXPECTED_GRAND_TOTAL = 96433.66
EXPECTED_LINE_ITEMS = 15

EXPECTED_INVOICES = {
    "CKD/25-26/1668",  # appears twice (different products), so 2 entries
    "CKD/25-26/1978",
    "CKD/25-26/1180",  # appears twice (different products), so 2 entries
    "CKD/25-26/1983",
    "CKD/25-26/1641",
    "CKD/25-26/1472",  # <-- the missing one (Bug A)
    "CKD/25-26/1425",
    "CKD/25-26/1516",
    "CKD/25-26/1981",
    "CKD/25-26/2073",
    "CKD/25-26/1026",
    "CKD/25-26/0826",
    "CKD/25-26/0596",
}


def main() -> None:
    pages = read_document(PDF)
    parsed = parse_document(PDF.name, pages)
    items = parsed["line_items"]

    print(f"PDF pages: {len(pages)}")
    print(f"Line items extracted: {len(items)}  (expected {EXPECTED_LINE_ITEMS})")

    qty_sum = sum(i.quantity for i in items)
    total_sum = round(sum(i.total_amount for i in items), 2)
    print(f"Sum quantity:   {qty_sum:>10}  (expected {EXPECTED_QTY})")
    print(f"Sum total_amt:  {total_sum:>10.2f}  (expected {EXPECTED_GRAND_TOTAL:.2f})")

    invoices_seen = {i.invoice_no for i in items if i.invoice_no}
    missing = EXPECTED_INVOICES - invoices_seen
    extra = invoices_seen - EXPECTED_INVOICES
    print(f"Unique vendor invoices: {len(invoices_seen)}  (expected {len(EXPECTED_INVOICES)})")
    if missing:
        print(f"  MISSING vendor invoices: {sorted(missing)}")
    if extra:
        print(f"  UNEXPECTED vendor invoices: {sorted(extra)}")

    junk = [i for i in items if i.quantity == 0.0 and i.total_amount == 0.0]
    if junk:
        print(f"\nJUNK rows (qty=0 and total=0):  {len(junk)}")
        for j in junk:
            print(f"   - product={j.product[:60]!r}  invoice_no={j.invoice_no!r}")

    print("\nAll line items:")
    print(
        f"{'#':<3} {'Inv No':<18} {'Date':<10} {'Qty':>4} {'Total':>10}  ASIN          EAN              Product"
    )
    for idx, it in enumerate(items, 1):
        print(
            f"{idx:<3} {it.invoice_no:<18} {it.invoice_date:<10} {it.quantity:>4.0f} "
            f"{it.total_amount:>10.2f}  {it.asin:<14}{it.ean:<16} {it.product[:50]}"
        )


if __name__ == "__main__":
    main()
