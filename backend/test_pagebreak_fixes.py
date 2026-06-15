"""Unit tests for partial ASIN, rate merge, and GSTIN-in-EAN fixes."""
import re

from app.extractors.pagebreak import (
    ASIN_RE,
    LineItem,
    looks_like_gstin_fragment,
    looks_like_new_item,
    merge_line_item_continuation,
    should_merge_continuation,
)
from app.models import SourceRef


def _item(**kwargs) -> LineItem:
    defaults = {"source_ref": SourceRef(page=1, confidence=0.8)}
    defaults.update(kwargs)
    return LineItem(**defaults)


def test_gstin_fragment_detection() -> None:
    assert looks_like_gstin_fragment("07AATCA003")
    assert looks_like_gstin_fragment("07AATCA0030E1Z5")
    assert not looks_like_gstin_fragment("5OMTSVFV")
    assert not looks_like_gstin_fragment("QQWDS3")


def test_tail_with_gstin_in_ean_is_not_new_item() -> None:
    tail = _item(
        page=2,
        asin="M71",
        ean="07AATCA003",
        hsn="85366990",
        product="with Universal Mounting Bracket",
        quantity=1.0,
        total_amount=361.96,
        tax_type="IGST",
        source_ref=SourceRef(page=2, confidence=0.8),
    )
    assert not looks_like_new_item(tail)


def test_partial_asin_merge_from_asin_column() -> None:
    head = _item(
        system_ref_no="2",
        asin="B0DX77J",
        product="Robustt Heavy Duty AC Stand",
        quantity=1.0,
        total_cost=306.75,
        total_amount=361.96,
        cost_per_unit=306.75,
    )
    tail = _item(
        asin="M71",
        ean="07AATCA003",
        product="with Universal Mounting Bracket",
        quantity=1.0,
        total_amount=4.0,
        tax_type="0",
        source_ref=SourceRef(page=2, confidence=0.8),
    )
    assert should_merge_continuation(head, tail, 2)
    merged = merge_line_item_continuation(head, tail)
    assert merged.asin == "B0DX77JM71"
    assert ASIN_RE.match(merged.asin)
    assert merged.ean == ""
    assert "Universal Mounting" in merged.product


def test_partial_asin_merge_etrade() -> None:
    head = _item(
        system_ref_no="2",
        asin="B0BZD2P3",
        hsn="40169",
        product="Aromahpure Scented Candles",
        quantity=1.0,
        total_cost=500.0,
        total_amount=590.0,
        cost_per_unit=500.0,
    )
    tail = _item(
        asin="XX",
        hsn="590",
        product="(55 Hours) Soy Wax",
        quantity=0.0,
        total_amount=4.0,
        source_ref=SourceRef(page=2, confidence=0.8),
    )
    merged = merge_line_item_continuation(head, tail)
    assert len(merged.asin) == 10
    assert merged.asin.startswith("B0")
    assert merged.hsn == "40169590"


def test_rate_fix_from_net_when_head_total_complete() -> None:
    head = _item(
        system_ref_no="2",
        asin="B0D9",
        product="Robustt SUV",
        quantity=1.0,
        total_cost=2091.2,
        total_amount=2467.6,
        cost_per_unit=209.0,
        tax_type="IGST",
    )
    tail = _item(
        asin="QQWDS3",
        product="Car Inflatable Bed",
        cost_per_unit=1.22,
        total_amount=4.0,
        tax_type="0",
        source_ref=SourceRef(page=2, confidence=0.8),
    )
    merged = merge_line_item_continuation(head, tail)
    assert merged.asin == "B0D9QQWDS3"
    assert abs(merged.cost_per_unit - 2091.2) < 0.01
    assert abs(merged.total_amount - 2467.6) < 0.01


def test_asin_tail_not_lost_on_description_row() -> None:
    """Tail rows with description + ASIN fragment must merge identifiers, not just text."""
    head = _item(
        system_ref_no="2",
        asin="B09ZHQZ",
        ean="07AATCA003",
        product="Robustt Anti Skid/AntiSlip",
        quantity=1.0,
        total_cost=506.49,
        total_amount=597.66,
    )
    tail = _item(
        asin="GQL",
        ean="9M1ZD",
        product="18mtr(guaranteed) X50mm (Pack of 1)",
        source_ref=SourceRef(page=2, confidence=0.8),
    )
    assert should_merge_continuation(head, tail, 2)
    merged = merge_line_item_continuation(head, tail)
    assert merged.asin == "B09ZHQZGQL"
    assert ASIN_RE.match(merged.asin)
    assert merged.ean == ""


def test_seventeen_box_column_merge() -> None:
    from app.extractors.pagebreak import merge_continuation_rows

    mapping = {
        "sl_no": 0,
        "description": 1,
        "hsn": 2,
        "asin": 3,
        "purchase_order_no": 5,
        "vendor_invoice_no": 6,
        "quantity": 11,
        "total_amount": 17,
    }
    head = [
        "2",
        "ROOTS & LEAF Garden Hose",
        "39269099",
        "B0DJ71CFM2",
        "",
        "PO123",
        "ETD/25-26/",
        "",
        "",
        "",
        "",
        "1",
        "",
        "",
        "",
        "",
        "",
        "137.82",
    ]
    tail = [
        "",
        "Spray Gun with 8 modes",
        "",
        "",
        "",
        "",
        "1668",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
    ]
    merged = merge_continuation_rows(head, tail, mapping)
    assert merged[0] == "2"
    assert "Garden Hose" in merged[1] and "Spray Gun" in merged[1]
    assert "1668" in merged[6] and "ETD" in merged[6]
    assert merged[17] == "137.82"


def test_clicktech_row_without_serial_is_new_item() -> None:
    from app.extractors.pagebreak import is_complete_row_without_serial, is_page_continuation_row

    mapping = {
        "sl_no": 0,
        "description": 1,
        "asin": 3,
        "purchase_order_no": 5,
        "vendor_invoice_no": 6,
        "quantity": 11,
        "total_amount": 15,
    }
    row = [
        "",
        "Robustt Wheel Lock | Red & Yellow",
        "",
        "B0B14VMGTQ",
        "",
        "2WTO31IW",
        "CKD/25-26/2444",
        "",
        "",
        "",
        "",
        "10",
        "",
        "",
        "",
        "1385.96",
    ]
    assert is_complete_row_without_serial(row, mapping)
    assert not is_page_continuation_row(row, mapping)

    tail = ["", "upto 200kg weight | Air Conditioner", "", "", "", "", "", ""]
    assert not is_complete_row_without_serial(tail, mapping)
    assert is_page_continuation_row(tail, mapping)


def test_clicktech_total_qty_footer_not_merged() -> None:
    from app.extractors.pagebreak import (
        _merge_raw_numeric_cell,
        is_page_continuation_row,
        is_table_footer_row,
        merge_continuation_rows,
    )

    mapping = {
        "sl_no": 0,
        "description": 1,
        "hsn": 2,
        "asin": 3,
        "ean": 4,
        "sku": 5,
        "vendor_invoice_no": 6,
        "vendor_invoice_date": 7,
        "unit_code": 8,
        "quantity": 9,
        "rate": 10,
        "taxable_value": 11,
        "tax_rate": 12,
        "tax_type": 13,
        "tax_amount": 14,
        "total_amount": 15,
    }
    head = [
        "",
        "Robustt Anti Skid/AntiSlip 18mtr(guaranteed) X50mm",
        "39199020",
        "B09ZHJ4W7J",
        "8904457613863",
        "8DWAQSVL",
        "CKD/25-26/2709",
        "21-MAR-26",
        "EACH",
        "1",
        "492.51",
        "492.51",
        "18",
        "IGST",
        "88.65",
        "581.16",
    ]
    footer = ["", "", "", "", "", "", "", "", "TOTAL\nQTY", "41", "", "", "", "", "", ""]
    assert is_table_footer_row(footer, mapping)
    assert not is_page_continuation_row(footer, mapping)
    assert _merge_raw_numeric_cell("quantity", "1", "41") == "1"
    merged = merge_continuation_rows(head, footer, mapping)
    assert merged[mapping["quantity"]] == "1"


def test_clicktech_total_label_row_not_merged() -> None:
    from app.extractors.pagebreak import is_page_continuation_row, is_table_footer_row

    mapping = {
        "sl_no": 0,
        "description": 1,
        "hsn": 2,
        "asin": 3,
        "ean": 4,
        "purchase_order_no": 5,
        "vendor_invoice_no": 6,
        "vendor_invoice_date": 7,
        "unit_code": 8,
        "quantity": 9,
        "rate": 10,
        "taxable_value": 11,
        "tax_rate": 12,
        "tax_type": 13,
        "tax_amount": 14,
        "total_amount": 15,
    }
    total_row = ["", "", "", "", "", "Total:", "193.41", "", ""]
    assert is_table_footer_row(total_row, mapping)
    assert not is_page_continuation_row(total_row, mapping)


def test_etrade_po_wrap_tail_not_appended_to_vendor_invoice() -> None:
    from app.extractors.pagebreak import merge_continuation_rows

    mapping = {
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
        "quantity": 10,
        "rate": 11,
        "taxable_value": 12,
        "tax_rate": 13,
        "tax_type": 14,
        "tax_amount": 15,
        "total_amount": 16,
    }
    head = [
        "2",
        "Roots & Leaf\n5M hose",
        "39173\n100",
        "B0F8\nW1S\nLWH",
        "",
        "DR\nOPS\nHIP-\nPO-\nFOU",
        "ETD/D\nF/25-\n26/08\n5",
        "18-\nOCT-\n2025",
        "149996078673552",
        "545463976014001",
        "1",
        "267.07",
        "267.07",
        "18.0\n0",
        "IGST",
        "48.07",
        "315.14",
    ]
    tail = [
        "",
        "Pattern Spray Gun…",
        "",
        "",
        "",
        "",
        "I",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
    ]
    merged = merge_continuation_rows(head, tail, mapping)
    inv = re.sub(r"\s+", "", merged[mapping["vendor_invoice_no"]])
    po = re.sub(r"\s+", "", merged[mapping["purchase_order_no"]])
    assert inv == "ETD/DF/25-26/085", inv
    assert po == "DROPSHIP-PO-FOUI", po


def test_clicktech_subtotal_not_appended_to_vendor_invoice() -> None:
    from app.extractors.pagebreak import merge_continuation_rows

    mapping = {
        "sl_no": 0,
        "description": 1,
        "hsn": 2,
        "asin": 3,
        "ean": 4,
        "purchase_order_no": 5,
        "vendor_invoice_no": 6,
        "vendor_invoice_date": 7,
        "unit_code": 8,
        "quantity": 9,
        "rate": 10,
        "taxable_value": 11,
        "tax_rate": 12,
        "tax_type": 13,
        "tax_amount": 14,
        "total_amount": 15,
    }
    head = [
        "",
        "Robustt TV Wall Mount",
        "83025000",
        "B0GBV646RB",
        "8904457632185",
        "DROPSHIP-PO-FWWL",
        "CTDF/26-\n27/0016",
        "21-APR-26",
        "EACH",
        "1",
        "431.84",
        "431.84",
        "18",
        "IGST",
        "77.73",
        "509.57",
    ]
    for tail, label in [
        (["", "", "", "", "", "Sub Total:", "499.30", "", ""], "subtotal"),
        (["", "", "", "", "", "Total:", "4,299.75", "", ""], "grand total"),
        (["", "", "", "", "", "Currency", "INR", "", ""], "currency"),
    ]:
        merged = merge_continuation_rows(head, tail, mapping)
        inv = re.sub(r"\s+", "", merged[mapping["vendor_invoice_no"]])
        assert inv == "CTDF/26-27/0016", f"{label}: {inv!r}"


def test_etrade_invoice_tail_shifted_into_date_column() -> None:
    from app.extractors.pagebreak import merge_continuation_rows

    mapping = {
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
        "quantity": 10,
        "rate": 11,
        "taxable_value": 12,
        "tax_rate": 13,
        "tax_type": 14,
        "tax_amount": 15,
        "total_amount": 16,
    }
    head = [
        "2",
        "Robustt SUV",
        "40169",
        "B0D9",
        "",
        "4EA",
        "ETD/2",
        "05-",
        "149",
        "546",
        "1",
        "2,09",
        "2,091.2",
        "18.0",
        "IGST",
        "376.42",
        "2,467.6",
    ]
    tail = [
        "",
        "Car Inflatable\nBed - Grey\n(Pack of 1)",
        "590",
        "",
        "QQW\nDS3",
        "",
        "6XF\nXE",
        "5-\n26/04\n03",
        "SEP-\n2025",
        "926\n774\n229\n552",
        "542\n171\n347\n001",
        "",
        "1.22",
        "2",
        "0",
        "",
        "4",
    ]
    merged = merge_continuation_rows(head, tail, mapping)
    inv = re.sub(r"\s+", "", merged[mapping["vendor_invoice_no"]])
    po = re.sub(r"\s+", "", merged[mapping["purchase_order_no"]])
    assert inv == "ETD/25-26/0403", inv
    assert po == "4EA6XFXE", po


def test_etrade_invoice_digit_tail_in_vendor_column() -> None:
    from app.extractors.pagebreak import merge_continuation_rows

    mapping = {
        "sl_no": 0,
        "description": 1,
        "hsn": 2,
        "asin": 3,
        "ean": 4,
        "purchase_order_no": 5,
        "vendor_invoice_no": 6,
        "vendor_invoice_date": 7,
        "quantity": 10,
        "rate": 11,
        "taxable_value": 12,
        "tax_rate": 13,
        "tax_type": 14,
        "tax_amount": 15,
        "total_amount": 16,
    }
    head = ["2", "Product", "40169", "B0D9", "", "4EA", "ETD/2\n5-\n26/07", "31-\nJAN-\n2026"] + [""] * 9
    tail = ["", "Desc tail", "", "", "", "", "91", ""] + [""] * 9
    merged = merge_continuation_rows(head, tail, mapping)
    inv = re.sub(r"\s+", "", merged[mapping["vendor_invoice_no"]])
    assert inv == "ETD/25-26/0791", inv


def test_etrade_df_invoice_not_truncated_by_strip() -> None:
    from app.extractors.pagebreak import _strip_summary_suffix

    assert _strip_summary_suffix("ETD/DF/24-25/205") == "ETD/DF/24-25/205"
    assert _strip_summary_suffix("ETD/DF/25-26/085") == "ETD/DF/25-26/085"


def main() -> None:
    test_gstin_fragment_detection()
    test_tail_with_gstin_in_ean_is_not_new_item()
    test_partial_asin_merge_from_asin_column()
    test_partial_asin_merge_etrade()
    test_rate_fix_from_net_when_head_total_complete()
    test_asin_tail_not_lost_on_description_row()
    test_seventeen_box_column_merge()
    test_clicktech_row_without_serial_is_new_item()
    test_clicktech_total_qty_footer_not_merged()
    test_clicktech_total_label_row_not_merged()
    test_etrade_po_wrap_tail_not_appended_to_vendor_invoice()
    test_etrade_invoice_tail_shifted_into_date_column()
    test_etrade_invoice_digit_tail_in_vendor_column()
    test_etrade_df_invoice_not_truncated_by_strip()
    test_clicktech_subtotal_not_appended_to_vendor_invoice()
    print("PASS: all pagebreak fix unit tests")


if __name__ == "__main__":
    main()
