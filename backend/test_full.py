"""Full ground-truth test against OK_26400352104832.pdf.

Every field from the PDF is asserted. Run after each parser change to see
which fields are right and which are still wrong.
"""
from pathlib import Path

from app.extractors import parse_document, read_document

PDF = Path(r"c:\Users\Inno\Downloads\OK_26400352104832.pdf")

EXPECTED = {
    "header": {
        "debit_note_number": "26400352104832",
        "debit_note_date": "09-MAR-2026",
        "rma_number": "RTVWK10-D403281123",
        "due_date": "09-MAR-2026",
        "return_id": "",
        "removal_id": "",
        "vret_shipment_id": "",
        "call_tag_id": "",
        "payment_method": "Deduct From Payment",
        "payment_terms": "IMMEDIATE",
        "reason": "Goods returned to vendor",
        "place_of_supply": "07-DELHI",
        "invoice_reference_number": "IRN not generated for this document. Not a valid tax document for GST purposes.",
        "currency": "INR",
        "irn": "",
        "document_number": "26400352104832",
        "document_date": "09-MAR-2026",
    },
    "vendor": {
        # the issuer of the R4C is Clicktech (left/billing column)
        "name": "Clicktech Retail Private Limited",
        "gstin": "06AAJCC9783E1ZB",
        "pan": "AAJCC9783E",  # from page footer ("PAN: AAJCC9783E")
    },
    "customer": {
        # the vendor being billed is AVA (right/receiver-billing column)
        "name": "AVA INTERNATIONAL PRIVATE LIMITED(1OLLS)",
        "gstin": "07AATCA0039M1ZD",
    },
    "billing_address": {
        "name": "Clicktech Retail Private Limited",
        "city": "Gurgaon",
        "state": "Haryana",
        "postal_code": "122413",
        "country": "India",
        "gstin": "06AAJCC9783E1ZB",
        "state_code": "HR",
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
        # In this PDF the shipping block has no company-name line for the
        # left column, so it should inherit from billing.
        "name": "Clicktech Retail Private Limited",
        "city": "Gurgaon",
        "state": "Haryana",
        "postal_code": "122413",
        "country": "India",
        "gstin": "06AAJCC9783E1ZB",
        "state_code": "HR",
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
        "grand_total": 96433.66,
    },
    "line_items": {
        "count": 15,
        "qty_sum": 176,
    },
}


def check(label: str, actual, expected) -> bool:
    actual_norm = (actual or "").strip() if isinstance(actual, str) else actual
    expected_norm = (expected or "").strip() if isinstance(expected, str) else expected
    ok = actual_norm == expected_norm
    if isinstance(expected, float):
        ok = abs(float(actual or 0) - expected) <= 0.05
    mark = "OK " if ok else "FAIL"
    print(f"  [{mark}] {label:<50}  expected={expected!r:<60}  actual={actual!r}")
    return ok


def main() -> None:
    pages = read_document(PDF)
    parsed = parse_document(PDF.name, pages)

    total_checks = 0
    failed = 0

    print("\n=== HEADER ===")
    for key, exp in EXPECTED["header"].items():
        total_checks += 1
        if not check(f"header.{key}", parsed["header"].get(key, ""), exp):
            failed += 1

    print("\n=== VENDOR ===")
    vendor = parsed["vendor"].model_dump() if hasattr(parsed["vendor"], "model_dump") else parsed["vendor"]
    for key, exp in EXPECTED["vendor"].items():
        total_checks += 1
        if not check(f"vendor.{key}", vendor.get(key, ""), exp):
            failed += 1

    print("\n=== CUSTOMER ===")
    customer = parsed["customer"].model_dump() if hasattr(parsed["customer"], "model_dump") else parsed["customer"]
    for key, exp in EXPECTED["customer"].items():
        total_checks += 1
        if not check(f"customer.{key}", customer.get(key, ""), exp):
            failed += 1

    for addr_key in ["billing_address", "shipping_address", "receiver_billing_address", "receiver_shipping_address"]:
        print(f"\n=== {addr_key.upper()} ===")
        actual = parsed[addr_key]
        for key, exp in EXPECTED[addr_key].items():
            total_checks += 1
            if not check(f"{addr_key}.{key}", actual.get(key, ""), exp):
                failed += 1

    print("\n=== TOTALS ===")
    for key, exp in EXPECTED["totals"].items():
        total_checks += 1
        if not check(f"totals.{key}", parsed["totals"].get(key, 0.0), exp):
            failed += 1

    print("\n=== LINE ITEMS ===")
    items = parsed["line_items"]
    total_checks += 1
    if not check("line_items.count", len(items), EXPECTED["line_items"]["count"]):
        failed += 1
    total_checks += 1
    if not check(
        "line_items.qty_sum",
        sum(i.quantity for i in items),
        EXPECTED["line_items"]["qty_sum"],
    ):
        failed += 1

    print("\n" + "=" * 100)
    passed = total_checks - failed
    print(f"  RESULT: {passed} / {total_checks} fields correct  ({failed} failures)")
    print("=" * 100)


if __name__ == "__main__":
    main()
