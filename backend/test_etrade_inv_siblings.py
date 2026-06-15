"""Sanity check: parse the 3 SIBLING ETRADE GST Invoices in the same folder
and confirm the parser produces sensible, unique output for each (no
regressions, no field bleed)."""
from pathlib import Path

from app.extractors import parse_document, read_document

FOLDER = Path(r"c:\Users\Inno\Downloads\GST Invoice (2)\GST Invoice")
SIBLINGS = ["30000877787.pdf", "30000877788.pdf", "30000877789.pdf"]

# Per-PDF expected anchors (verified by eyeballing the inspect output earlier).
# Each tuple is (system_ref_no, vendor_state_code, customer_pan).
EXPECTED = {
    "30000877787.pdf": ("30000877787", "GJ", "AATCA0039M"),
    "30000877788.pdf": ("30000877788", "KA", "AATCA0039M"),
    "30000877789.pdf": ("30000877789", "WB", "AATCA0039M"),
}

failed = 0
total = 0

for fname in SIBLINGS:
    print(f"\n=== {fname} ===")
    pdf = FOLDER / fname
    pages = read_document(pdf)
    parsed = parse_document(fname, pages)

    h = parsed["header"]
    bill = parsed["billing_address"]
    rcv = parsed["receiver_billing_address"]
    items = parsed["line_items"]

    print(f"  type:           {parsed['document_type']}")
    print(f"  inv_num:        {h.get('invoice_number')}")
    print(f"  inv_date:       {h.get('invoice_date')}")
    print(f"  system_ref_no:  {h.get('system_ref_no')}")
    print(f"  vendor:         {parsed['vendor'].name}  GSTIN={parsed['vendor'].gstin}  PAN={parsed['vendor'].pan}")
    print(f"  customer:       {parsed['customer'].name}  GSTIN={parsed['customer'].gstin}")
    print(f"  bill addr:      {bill.get('city')}, {bill.get('state')} {bill.get('postal_code')}  ({bill.get('state_code')})")
    print(f"  rcv addr:       {rcv.get('city')}, {rcv.get('state')} {rcv.get('postal_code')}  ({rcv.get('state_code')}) PAN={rcv.get('pan')}")
    print(f"  total:          {parsed['totals'].get('grand_total')}")
    print(f"  line items:     count={len(items)}  qty_sum={sum(i.quantity for i in items)}  total_sum={round(sum(i.total_amount for i in items), 2)}")

    sys_ref, state_code, cust_pan = EXPECTED[fname]
    checks = [
        ("document_type",        str(parsed["document_type"]) == "DocumentType.invoice"),
        ("system_ref_no",        h.get("system_ref_no") == sys_ref),
        ("vendor.pan",           parsed["vendor"].pan == "AADCV4254H"),
        ("vendor.state_code",    bill.get("state_code") == state_code),
        ("customer.gstin",       parsed["customer"].gstin == "07AATCA0039M1ZD"),
        ("customer_pan",         rcv.get("pan") == cust_pan),
        ("addr.city_present",    bool(bill.get("city")) and bool(rcv.get("city"))),
        ("addr.state_present",   bool(bill.get("state")) and bool(rcv.get("state"))),
        ("totals.grand_total>0", parsed["totals"].get("grand_total", 0) > 0),
        ("line_items_present",   len(items) > 0),
        ("line_total≈grand",     abs(sum(i.total_amount for i in items) - parsed["totals"].get("grand_total", 0)) < 1.0),
    ]
    for name, ok in checks:
        total += 1
        mark = "OK " if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"    [{mark}] {name}")

print(f"\n{'=' * 80}\n  {total - failed} / {total} sanity checks passed across {len(SIBLINGS)} ETRADE invoices\n{'=' * 80}")
