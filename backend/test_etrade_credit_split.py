"""ETRADE GST Credit Note page-break split regression (42000095407 pattern)."""
from __future__ import annotations

from app.extractors.parser import _extract_line_items, _map_columns
from app.models import DocumentType, Party, RawPage

HEADER = [
    "SI.N",
    "Item Description",
    "HSN/SAC",
    "ASIN Code",
    "UPC/EAN",
    "PO NO",
    "Vendor Invoice No",
    "Vendor Invoice Date",
    "Return ID",
    "Shipment ID",
    "Unit/Code",
    "Qty",
    "Price Per Unit",
    "Net Amount",
    "Tax Rate %",
    "Tax Type",
    "Tax Amount",
    "Total Amount",
]

# Page 1 item 1 (complete) — Green raincoat, qty 2
ROW1 = [
    "1",
    "Robustt Unisex Raincoat with Hood - Green (Pack of 10)",
    "62014090",
    "B0D8PW2FZV",
    "2E7GQ",
    "ROBUSTTPN1HR",
    "ETD/25-26/0207",
    "12-JUL-2025",
    "65233221756552",
    "",
    "EACH",
    "2",
    "967.40",
    "1934.80",
    "5.00",
    "IGST",
    "-96.74",
    "-2031.54",
]

# Page 1 item 2 head — only product name (split mid-row)
ROW2_HEAD = [
    "2",
    "Robustt",
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
    "",
    "",
    "",
    "",
    "",
]

# Page 2 item 2 tail — empty Sl. No., rest of description + identifiers
ROW2_TAIL = [
    "",
    "Unisex Raincoat with Hood - Dark Grey (Pack of 1)",
    "62014090",
    "B0D8PY29SK",
    "",
    "3D5PN1HR",
    "ETD/25-26/0307",
    "04-AUG-2025",
    "65233221756552",
    "",
    "EACH",
    "9",
    "-130.52",
    "-1174.68",
    "5.00",
    "IGST",
    "-58.73",
    "-1233.41",
    "",
]

# Page 2 item 3 (complete)
ROW3 = [
    "3",
    "Robustt Unisex Raincoat with Hood - Dark Grey (Pack of 1)",
    "62014090",
    "B0D8PY29SK",
    "",
    "3D5PN1HR",
    "ETD/25-26/0307",
    "04-AUG-2025",
    "65233221756552",
    "",
    "EACH",
    "1",
    "-130.52",
    "-130.52",
    "5.00",
    "IGST",
    "-6.53",
    "-137.05",
    "",
]


def _pages() -> list[RawPage]:
    return [
        RawPage(
            page_number=1,
            raw_text="GST Credit Note\nTotal Qty: 12",
            tables=[{"rows": [HEADER, ROW1, ROW2_HEAD]}],
        ),
        RawPage(
            page_number=2,
            raw_text="Total Qty: 12\nTotal: -3,402.00",
            tables=[{"rows": [ROW2_TAIL, ROW3]}],
        ),
    ]


def test_partial_head_kept_and_merged_with_tail() -> None:
    header = {"document_number": "MHCN2026-1975", "document_date": "20-Apr-2026"}
    vendor = Party(name="ETRADE MARKETING PRIVATE LIMITED", gstin="27AADCV4254H1Z8")
    items = _extract_line_items(_pages(), header, DocumentType.credit_note, vendor)

    assert len(items) == 3, f"expected 3 items, got {len(items)}"
    assert items[0].system_ref_no == "1"
    assert items[1].system_ref_no == "2"
    assert items[2].system_ref_no == "3"
    assert "Green" in items[0].product
    assert abs(items[0].total_amount - (-2031.54)) < 0.05
    assert "Dark Grey" in items[1].product
    assert abs(items[1].total_amount - (-1233.41)) < 0.05
    assert abs(items[2].total_amount - (-137.05)) < 0.05
    assert round(sum(i.quantity for i in items), 2) == 12.0


def test_map_columns_on_header() -> None:
    mapping = _map_columns(HEADER)
    assert mapping.get("sl_no") == 0
    assert mapping.get("total_amount") is not None


def main() -> None:
    test_map_columns_on_header()
    test_partial_head_kept_and_merged_with_tail()
    print("PASS: ETRADE credit note split tests")


if __name__ == "__main__":
    main()
