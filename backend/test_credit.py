"""Full ground-truth test against 27421653100006.pdf (Format 3 — Clicktech GST Credit Note)."""
from pathlib import Path

from app.extractors import parse_document, read_document
from app.models import DocumentType

PDF = Path(r"c:\Users\Inno\Downloads\GST Credit Note\GST Credit Note\27421653100006.pdf")

EXPECTED = {
    "document_type": DocumentType.credit_note,
    "header": {
        "credit_note_number": "27421653100006",
        "credit_note_date": "06-APR-2026",
        "document_number": "27421653100006",
        "document_date": "06-APR-2026",
        "rma_number": "5791299231",
        "due_date": "06-APR-2026",
        "return_id": "148757339523552",
        "removal_id": "5791299231",
        "payment_method": "Deduct From Payment",
        "payment_terms": "",
        "reason": "Cancellation of debit Note note/Cancellation of Invoice",
        "vret_shipment_id": "",
        "call_tag_id": "",
        "place_of_supply": "07-DELHI",
        "invoice_reference_number": "6613ca73a587ce7aaa2154a91000a9157583b5265b4f4d024c83951573e61a7d",
        "irn": "6613ca73a587ce7aaa2154a91000a9157583b5265b4f4d024c83951573e61a7d",
        "currency": "INR",
        "original_invoice_number": "26421651105580",
        "original_invoice_date": "27-MAR-2026",
        "invoice_number": "",
        "invoice_date": "",
        "debit_note_number": "",
        "debit_note_date": "",
    },
    "vendor": {
        "name": "Clicktech Retail Private Limited",
        "gstin": "19AAJCC9783E1Z4",
        "pan": "AAJCC9783E",
    },
    "customer": {
        "name": "AVA INTERNATIONAL PRIVATE LIMITED(1OLLS)",
        "gstin": "07AATCA0039M1ZD",
    },
    "billing_address": {
        "name": "Clicktech Retail Private Limited",
        "city": "Howrah",
        "state": "West Bengal",
        "postal_code": "711302",
        "country": "India",
        "gstin": "19AAJCC9783E1Z4",
        "state_code": "WB",
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
        "city": "Howrah",
        "state": "West Bengal",
        "postal_code": "711302",
        "country": "India",
        "gstin": "19AAJCC9783E1Z4",
        "state_code": "WB",
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
        "grand_total": 1541.15,
    },
    "line_items": {
        "count": 4,
        "qty_sum": 4,
        "item_1": {
            "combo": "5ZQXBIYT",
            "invoice_no": "CKD/25-26/2167",
            "ean": "",
        },
        "item_4": {
            "combo": "8R5CCA6C",
            "invoice_no": "CKD/25-26/2270",
            "ean": "",
        },
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

    # Per-item code sanity (none should be a GSTIN-shaped value)
    print("\n=== LINE-ITEM CODE SANITY ===")
    import re
    GSTIN = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z]\d$")
    for i, item in enumerate(items, 1):
        for fname in ["ean", "asin", "sku", "combo"]:
            v = getattr(item, fname, "")
            if v and GSTIN.match(v):
                total += 1
                failed += 1
                print(f"  [FAIL] line_items[{i}].{fname} should NOT be a GSTIN  actual={v!r}")

    print("\n=== LINE-ITEM PO / VENDOR INVOICE ===")
    for key in ("item_1", "item_4"):
        spec = EXPECTED["line_items"][key]
        idx = int(key.split("_")[1]) - 1
        item = items[idx]
        for field, exp in spec.items():
            total += 1
            if not check(f"line_items[{idx + 1}].{field}", getattr(item, field, ""), exp):
                failed += 1

    print("\n" + "=" * 110)
    print(f"  RESULT: {total - failed} / {total} fields correct  ({failed} failures)")
    print("=" * 110)


if __name__ == "__main__":
    main()
