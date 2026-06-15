"""Full ground-truth test against GST Formmate.pdf (Type 2 — Clicktech GST Invoice)."""
from pathlib import Path

from app.extractors import parse_document, read_document
from app.models import DocumentType

PDF = Path(r"c:\Users\Inno\Downloads\GST Formmate.pdf")

EXPECTED = {
    "document_type": DocumentType.invoice,
    "header": {
        "invoice_number": "27408051103016",
        "invoice_date": "30-MAY-2026",
        "document_number": "27408051103016",
        "document_date": "30-MAY-2026",
        "rma_number": "RTVWk20-D450674875",
        "due_date": "30-MAY-2026",
        "return_id": "",
        "removal_id": "",
        "vret_shipment_id": "",
        "call_tag_id": "",
        "payment_method": "Deduct From Payment",
        "payment_terms": "IMMEDIATE",
        "reason": "",  # GST Invoice has no "Reason for Issuing Debit"
        "place_of_supply": "07-DELHI",
        "invoice_reference_number": "fc45ee7d6563846491463864ab29e4956006666eadc1d5ca1e416d9704a21722",
        "irn": "fc45ee7d6563846491463864ab29e4956006666eadc1d5ca1e416d9704a21722",
        "currency": "INR",
        "debit_note_number": "",
        "debit_note_date": "",
    },
    "vendor": {
        "name": "Clicktech Retail Private Limited",
        "gstin": "27AAJCC9783E1Z7",
        "pan": "AAJCC9783E",
    },
    "customer": {
        "name": "AVA INTERNATIONAL PRIVATE LIMITED(1OLLS)",
        "gstin": "07AATCA0039M1ZD",
    },
    "billing_address": {
        "name": "Clicktech Retail Private Limited",
        "city": "Thane",
        "state": "Maharashtra",
        "postal_code": "421302",
        "country": "India",
        "gstin": "27AAJCC9783E1Z7",
        "state_code": "MH",
        "pan": "",
    },
    "receiver_billing_address": {
        "name": "AVA INTERNATIONAL PRIVATE LIMITED(1OLLS)",
        "city": "ALIPUR, NEW DELHI",
        "state": "DELHI",
        "postal_code": "110036",
        "country": "INDIA",
        "gstin": "07AATCA0039M1ZD",
        "state_code": "DL",
        "pan": "",
    },
    "shipping_address": {
        "name": "Clicktech Retail Private Limited",
        "city": "Thane",
        "state": "Maharashtra",
        "postal_code": "421302",
        "country": "India",
        "gstin": "27AAJCC9783E1Z7",
        "state_code": "MH",
        "pan": "",
    },
    "receiver_shipping_address": {
        "name": "AVA INTERNATIONAL PRIVATE LIMITED(1OLLS)",
        "city": "ALIPUR, NEW DELHI",
        "state": "DELHI",
        "postal_code": "110036",
        "country": "INDIA",
        "gstin": "07AATCA0039M1ZD",
        "state_code": "DL",
        "pan": "",
        "place_of_supply": "07-DELHI",
    },
    "totals": {
        "grand_total": 96075.79,
    },
    "line_items": {
        "count": 29,
        "qty_sum": 211,
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
        print(f"  [FAIL] document_type                                expected={EXPECTED['document_type']!r}  actual={actual_type!r}")
    else:
        print(f"  [OK ] document_type                                expected={EXPECTED['document_type']!r}  actual={actual_type!r}")

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

    print("\n" + "=" * 110)
    print(f"  RESULT: {total - failed} / {total} fields correct  ({failed} failures)")
    print("=" * 110)


if __name__ == "__main__":
    main()
