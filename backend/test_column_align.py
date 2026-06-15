"""Column-count alignment tests."""
from app.extractors.column_align import (
    expected_column_count,
    normalize_table_row,
    score_row_alignment,
)

MAPPING = {
    "sl_no": 0,
    "description": 1,
    "hsn": 2,
    "asin": 3,
    "ean": 4,
    "purchase_order_no": 5,
    "vendor_invoice_no": 6,
    "vendor_invoice_date": 7,
    "return_id": 8,
    "shipment_id": 9,
    "unit_code": 10,
    "quantity": 11,
    "rate": 12,
    "taxable_value": 13,
    "tax_rate": 14,
    "tax_type": 15,
    "tax_amount": 16,
    "total_amount": 17,
}


def test_expected_seventeen_columns() -> None:
    assert expected_column_count(MAPPING) == 18  # indices 0-17


def test_trim_extra_empty_column() -> None:
    # Extra empty column shifts vendor invoice into PO slot
    row = [
        "2",
        "Product name here",
        "39269099",
        "B0DG8RZX7H",
        "",
        "",
        "424VKC9C",
        "CKD/25-26/1977",
        "",
        "EACH",
        "1",
        "466.84",
        "466.84",
        "18",
        "IGST",
        "84.03",
        "550.87",
        "",
    ]
    assert len(row) == 18
    normalized = normalize_table_row(row, MAPPING, continuation=True)
    assert len(normalized) == 18
    assert score_row_alignment(normalized, MAPPING) >= score_row_alignment(row, MAPPING)


def test_serial_row_skips_reassignment() -> None:
    mapping = {
        "sl_no": 0,
        "description": 1,
        "total_amount": 17,
    }
    row = ["2", "Robustt", ""] + [""] * 15
    normalized = normalize_table_row(row, mapping, continuation=False)
    assert normalized[0] == "2"
    assert normalized[1] == "Robustt"


def main() -> None:
    test_expected_seventeen_columns()
    test_trim_extra_empty_column()
    test_serial_row_skips_reassignment()
    print("PASS: column align tests")


if __name__ == "__main__":
    main()
