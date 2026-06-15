"""Sanity check: ETRADE R4C siblings in the same folder."""
from pathlib import Path

from app.extractors import parse_document, read_document

FOLDER = Path(r"c:\Users\Inno\Downloads\Request for Credit (1)\Request for Credit")
SIBLINGS = ["31000195995.pdf", "31000196093.pdf"]

for fname in SIBLINGS:
    print(f"\n=== {fname} ===")
    pdf = FOLDER / fname
    parsed = parse_document(fname, read_document(pdf))
    h = parsed["header"]
    items = parsed["line_items"]
    gt = parsed["totals"].get("grand_total", 0)
    ls = round(sum(i.total_amount for i in items), 2)
    print(f"  type={parsed['document_type']}  debit={h.get('debit_note_number')}  ref={h.get('system_ref_no')}")
    print(f"  vendor={parsed['vendor'].gstin}  customer={parsed['customer'].gstin}")
    print(f"  bill_city={parsed['billing_address'].get('city')}  ship_city={parsed['shipping_address'].get('city')}")
    print(f"  reason={h.get('reason')!r}")
    print(f"  items={len(items)} qty={sum(i.quantity for i in items)} grand={gt} line_sum={ls}")

print("\nDone.")
