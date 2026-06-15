"""Sanity check: ETRADE Cancellation sibling 33000009258.pdf."""
from pathlib import Path

from app.extractors import parse_document, read_document

PDF = Path(r"c:\Users\Inno\Downloads\Cancellation Request for Credit\Cancellation Request for Credit\33000009258.pdf")

pages = read_document(PDF)
parsed = parse_document(PDF.name, pages)
h = parsed["header"]
items = parsed["line_items"]

print(f"type:          {parsed['document_type']}")
print(f"credit_note:   {h.get('credit_note_number')}")
print(f"system_ref:    {h.get('system_ref_no')}")
print(f"orig_inv:      {h.get('original_invoice_number')}")
print(f"reason:        {h.get('reason')}")
print(f"grand_total:   {parsed['totals'].get('grand_total')}")
print(f"line items:    {len(items)}  qty={sum(i.quantity for i in items)}  sum={round(sum(i.total_amount for i in items), 2)}")

checks = [
    str(parsed["document_type"]).endswith("credit_note"),
    h.get("credit_note_number") == "HRCN2025-27533",
    h.get("system_ref_no") == "33000009258",
    h.get("original_invoice_number") == "31000190362",
    h.get("reason") == "Cancellation of debit note/Invoice",
    parsed["vendor"].pan == "AADCV4254H",
    parsed["customer"].gstin == "07AATCA0039M1ZD",
    len(items) == 2,
    abs(parsed["totals"].get("grand_total", 0) + 354.30) < 0.05,
    abs(sum(i.total_amount for i in items) + 354.30) < 0.05,
]
failed = sum(1 for c in checks if not c)
print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
