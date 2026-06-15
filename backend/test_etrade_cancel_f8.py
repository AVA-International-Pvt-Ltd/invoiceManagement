"""Full ground-truth test against 33000009506.pdf
(Format 8 — ETRADE Cancellation of Request for Credit, Shipment ID variant)."""
from pathlib import Path

from app.extractors import parse_document, read_document
from app.models import DocumentType

PDF = Path(r"c:\Users\Inno\Downloads\Cancellation for Credit requst\Cancellation for Credit requst\33000009506.pdf")

EXPECTED = {
    "document_type": DocumentType.credit_note,
    "header": {
        "credit_note_number": "HRCN2025-37126",
        "credit_note_date": "13-Feb-2026",
        "document_number": "HRCN2025-37126",
        "document_date": "13-Feb-2026",
        "system_ref_no": "33000009506",
        "rma_number": "",
        "due_date": "13-Feb-2026",
        "return_id": "",
        "removal_id": "",
        "payment_method": "Deduct from Payment",
        "payment_terms": "",
        "reason": "Cancellation of debit note/Invoice",
        "vret_shipment_id": "",
        "call_tag_id": "",
        "place_of_supply": "07-Delhi",
        "invoice_reference_number": "IRN not generated for this document. Not a valid tax document for GST purposes.",
        "irn": "",
        "currency": "INR",
        "original_invoice_number": "31000229642",
        "original_invoice_date": "09-FEB-2026",
        "invoice_number": "",
        "invoice_date": "",
        "debit_note_number": "",
        "debit_note_date": "",
    },
    "vendor": {
        "name": "ETRADE MARKETING PRIVATE LIMITED",
        "gstin": "06AADCV4254H1ZC",
        "pan": "AADCV4254H",
    },
    "customer": {
        "name": "AVA International Private Limited(UR7GC)",
        "gstin": "07AATCA0039M1ZD",
    },
    "billing_address": {
        "name": "ETRADE MARKETING PRIVATE LIMITED",
        "city": "GURUGRAM",
        "state": "Haryana",
        "postal_code": "121102",
        "gstin": "06AADCV4254H1ZC",
        "state_code": "HR",
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
        "city": "GURUGRAM",
        "state": "Haryana",
        "postal_code": "121102",
        "gstin": "06AADCV4254H1ZC",
        "state_code": "HR",
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
        "grand_total": -1224.33,
    },
    "line_items": {
        "count": 1,
        "qty_sum": 1,
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

    print("\n=== LINE ITEMS DETAIL ===")
    for i, it in enumerate(items, 1):
        print(f"  {i}: Sl={it.system_ref_no!r}  ASIN={it.asin!r}  PO={it.combo!r}  qty={it.quantity}  cost={it.total_cost}  total={it.total_amount}")

    print("\n" + "=" * 110)
    print(f"  RESULT: {total - failed} / {total} fields correct  ({failed} failures)")
    print("=" * 110)


if __name__ == "__main__":
    main()
