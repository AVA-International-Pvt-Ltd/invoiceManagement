"""Full ground-truth test against 30000877790.pdf
(Format 5 — ETRADE GST Invoice)."""
from pathlib import Path

from app.extractors import parse_document, read_document
from app.models import DocumentType

PDF = Path(r"c:\Users\Inno\Downloads\GST Invoice (2)\GST Invoice\30000877790.pdf")

EXPECTED = {
    "document_type": DocumentType.invoice,
    "header": {
        "invoice_number": "MHIN2025-196600",
        "invoice_date": "01-Dec-2025",
        "document_number": "MHIN2025-196600",
        "document_date": "01-Dec-2025",
        "rma_number": "",
        "due_date": "01-Dec-2025",
        "return_id": "",
        "removal_id": "",
        "payment_method": "Deduct from Payment",
        "payment_terms": "Pay on Receipt",
        "reason": "",
        "vret_shipment_id": "",
        "call_tag_id": "",
        "place_of_supply": "07-Delhi",
        "invoice_reference_number": "02f1aa2b78d8963dd5719bceb920661e7a4e1a57ae71db1894cb57858c9b0555",
        "irn": "02f1aa2b78d8963dd5719bceb920661e7a4e1a57ae71db1894cb57858c9b0555",
        "currency": "INR",
        "system_ref_no": "30000877790",
        "original_invoice_number": "",
        "original_invoice_date": "",
        "credit_note_number": "",
        "credit_note_date": "",
        "debit_note_number": "",
        "debit_note_date": "",
    },
    "vendor": {
        "name": "ETRADE MARKETING PRIVATE LIMITED",
        "gstin": "27AADCV4254H1Z8",
        "pan": "AADCV4254H",
    },
    "customer": {
        "name": "AVA International Private Limited(UR7GC)",
        "gstin": "07AATCA0039M1ZD",
    },
    "billing_address": {
        "name": "ETRADE MARKETING PRIVATE LIMITED",
        "city": "NAGPUR",
        "state": "Maharashtra",
        "postal_code": "440018",
        "gstin": "27AADCV4254H1Z8",
        "state_code": "MH",
    },
    "receiver_billing_address": {
        "name": "AVA International Private Limited(UR7GC)",
        "city": "NEW DELHI",
        "state": "Delhi",
        "postal_code": "110036",
        "gstin": "07AATCA0039M1ZD",
        "state_code": "DL",
        "pan": "AATCA0039M",
    },
    "shipping_address": {
        "name": "ETRADE MARKETING PRIVATE LIMITED",
        "city": "NAGPUR",
        "state": "Maharashtra",
        "postal_code": "440018",
        "gstin": "27AADCV4254H1Z8",
        "state_code": "MH",
    },
    "receiver_shipping_address": {
        "name": "AVA International Private Limited(UR7GC)",
        "city": "NEW DELHI",
        "state": "Delhi",
        "postal_code": "110036",
        "gstin": "07AATCA0039M1ZD",
        "state_code": "DL",
        "pan": "AATCA0039M",
        "place_of_supply": "07-Delhi",
    },
    "totals": {
        "grand_total": 2598.50,
    },
    "line_items": {
        "count": 2,
        "qty_sum": 12,
    },
}


def check(label: str, actual, expected) -> bool:
    actual_norm = (actual or "").strip() if isinstance(actual, str) else actual
    expected_norm = (expected or "").strip() if isinstance(expected, str) else expected
    ok = actual_norm == expected_norm
    if isinstance(expected, float):
        ok = abs(float(actual or 0) - expected) <= 0.05
    mark = "OK " if ok else "FAIL"
    print(f"  [{mark}] {label:<50}  expected={expected!r:<70}  actual={actual!r}")
    return ok


def main() -> None:
    pages = read_document(PDF)
    parsed = parse_document(PDF.name, pages)

    total = 0
    failed = 0

    print(f"\n=== DOCUMENT TYPE ===")
    total += 1
    actual_type = parsed["document_type"]
    if actual_type != EXPECTED["document_type"]:
        failed += 1
        print(f"  [FAIL] document_type   expected={EXPECTED['document_type']!r}  actual={actual_type!r}")
    else:
        print(f"  [OK ] document_type   expected={EXPECTED['document_type']!r}  actual={actual_type!r}")

    print("\n=== HEADER ===")
    for key, exp in EXPECTED["header"].items():
        total += 1
        if not check(f"header.{key}", parsed["header"].get(key, ""), exp):
            failed += 1

    print("\n=== VENDOR ===")
    vendor = parsed["vendor"].model_dump() if hasattr(parsed["vendor"], "model_dump") else parsed["vendor"]
    for key, exp in EXPECTED["vendor"].items():
        total += 1
        if not check(f"vendor.{key}", vendor.get(key, ""), exp):
            failed += 1

    print("\n=== CUSTOMER ===")
    customer = parsed["customer"].model_dump() if hasattr(parsed["customer"], "model_dump") else parsed["customer"]
    for key, exp in EXPECTED["customer"].items():
        total += 1
        if not check(f"customer.{key}", customer.get(key, ""), exp):
            failed += 1

    for addr_key in ["billing_address", "shipping_address", "receiver_billing_address", "receiver_shipping_address"]:
        print(f"\n=== {addr_key.upper()} ===")
        actual = parsed[addr_key]
        for key, exp in EXPECTED[addr_key].items():
            total += 1
            if not check(f"{addr_key}.{key}", actual.get(key, ""), exp):
                failed += 1

    print("\n=== TOTALS ===")
    for key, exp in EXPECTED["totals"].items():
        total += 1
        if not check(f"totals.{key}", parsed["totals"].get(key, 0.0), exp):
            failed += 1

    print("\n=== LINE ITEMS ===")
    items = parsed["line_items"]
    total += 1
    if not check("line_items.count", len(items), EXPECTED["line_items"]["count"]):
        failed += 1
    total += 1
    if not check("line_items.qty_sum", sum(i.quantity for i in items), EXPECTED["line_items"]["qty_sum"]):
        failed += 1

    # Print line items for diagnostic
    print("\n=== LINE ITEMS DETAIL ===")
    for i, it in enumerate(items, 1):
        print(f"  {i}: Sl={it.system_ref_no!r}  ASIN={it.asin!r}  EAN={it.ean!r}  PO={it.combo!r}  inv_no={it.invoice_no!r}  qty={it.quantity}  total={it.total_amount}")

    print("\n" + "=" * 110)
    print(f"  RESULT: {total - failed} / {total} fields correct  ({failed} failures)")
    print("=" * 110)


if __name__ == "__main__":
    main()
