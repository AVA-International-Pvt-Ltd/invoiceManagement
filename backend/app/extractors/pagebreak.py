"""Reusable page-break line item detection and merge for all document formats.

When pdfplumber splits a table row across pages, the head row (page N) carries
sl_no + partial codes/totals and the tail row (page N+1) has an empty sl_no
cell plus the remaining description, identifiers, and sometimes financial fields.

This module detects those tail rows and merges them into a single LineItem.
"""
from __future__ import annotations

import re
from typing import Any

from ..models import LineItem
from .column_align import expected_column_count, normalize_table_row

# Table columns merged box-by-box when page 2+ starts with an empty Sl. No. cell.
BOX_MERGE_CODE_FIELDS = frozenset(
    {
        "hsn",
        "asin",
        "ean",
        "sku",
        "purchase_order_no",
        "return_id",
        "shipment_id",
        "vendor_invoice_no",
    }
)
BOX_MERGE_NUMERIC_FIELDS = frozenset(
    {"quantity", "rate", "taxable_value", "tax_rate", "tax_amount", "total_amount"}
)

ASIN_RE = re.compile(r"^B0[A-Z0-9]{8}$")
GSTIN_FULL_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z]\d[Z][A-Z\d]$", re.I)
MAX_PLAUSIBLE_QTY = 10_000
TOTAL_QTY_RE = re.compile(r"Total Qty:\s*(\d+)", re.I)
SUMMARY_PHRASES = ("sub total", "subtotal", "grand total", "total qty", "for igst", "for cgst")
SUMMARY_POLLUTION_MARKERS = (
    "totalqty",
    "subtotal",
    "currency",
    "grandtotal",
    "totalinvoice",
    "forigst",
    "forcgst",
)

IDENTIFIER_FIELDS = (
    "asin",
    "ean",
    "sku",
    "hsn",
    "purchase_order_no",
    "vendor_invoice_no",
    "vendor_invoice_date",
    "return_id",
    "shipment_id",
    "unit_code",
)

NUMERIC_FIELDS = (
    "quantity",
    "rate",
    "taxable_value",
    "tax_amount",
    "total_amount",
    "tax_rate",
)


def _clean_cell(value: str) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\n", " ")).strip()


def _clean_code(value: str) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", "", value)


def _clean_product(value: str) -> str:
    return _clean_cell(value)


def is_summary_row(product: str) -> bool:
    lowered = (product or "").lower()
    return any(phrase in lowered for phrase in SUMMARY_PHRASES)


def _cell_is_summary_label(value: str) -> bool:
    """True when a table cell is a footer/summary label (Total Qty, Sub Total, etc.)."""
    cell = _clean_cell(value)
    compact = re.sub(r"[^a-z0-9]", "", cell.lower())
    if not compact:
        return False
    if compact in {"total", "subtotal", "currency", "inr", "totalqty"}:
        return True
    if any(marker in compact for marker in SUMMARY_POLLUTION_MARKERS):
        return True
    if re.match(r"^(?:sub\s*)?total\s*:?\s*$", cell, re.I):
        return True
    if cell.upper() in {"CURRENCY", "INR"}:
        return True
    return is_summary_row(cell)


def is_table_footer_row(row: list[str], mapping: dict[str, int]) -> bool:
    """True for invoice table footer rows that must not merge into the last line item."""
    if _cell_is_summary_label(row_description(row, mapping)):
        return True
    for field in IDENTIFIER_FIELDS:
        if _cell_is_summary_label(_cell_raw(row, mapping, field)):
            return True
    return False


def row_serial_number(row: list[str], mapping: dict[str, int]) -> str:
    idx = mapping.get("sl_no")
    if idx is None or idx >= len(row):
        return ""
    return _clean_cell(row[idx])


def row_description(row: list[str], mapping: dict[str, int]) -> str:
    idx = mapping.get("description")
    if idx is None:
        sl_idx = mapping.get("sl_no")
        if sl_idx is not None and sl_idx + 1 < len(row):
            idx = sl_idx + 1
        elif len(row) > 1:
            idx = 1
    if idx is None or idx >= len(row):
        return ""
    return _clean_product(row[idx] or "")


def _cell_raw(row: list[str], mapping: dict[str, int], field: str) -> str:
    idx = mapping.get(field)
    if idx is None or idx >= len(row):
        return ""
    return (row[idx] or "").strip()


def _row_has_identifier_or_numeric_cells(row: list[str], mapping: dict[str, int]) -> bool:
    """True when a continuation row carries data outside the description column."""
    for field in IDENTIFIER_FIELDS:
        val = _clean_cell(_cell_raw(row, mapping, field))
        if val:
            return True
    for field in NUMERIC_FIELDS:
        idx = mapping.get(field)
        if idx is not None and idx < len(row) and _cell_float(row[idx]) != 0:
            return True
    return False


def _row_has_continuation_identifiers(row: list[str], mapping: dict[str, int]) -> bool:
    for field in IDENTIFIER_FIELDS:
        val = _clean_code(_cell_raw(row, mapping, field))
        if not val:
            continue
        if field == "unit_code" and _cell_is_summary_label(val):
            continue
        if field == "purchase_order_no" and _cell_is_summary_label(_cell_raw(row, mapping, field)):
            continue
        if len(val) >= 2 or _looks_like_asin_fragment(val):
            return True
    return False


def is_complete_row_without_serial(row: list[str], mapping: dict[str, int]) -> bool:
    """Clicktech credit notes often omit Sl. No. but the row is still a full line item."""
    if row_serial_number(row, mapping):
        return False

    asin = _clean_code(_cell_raw(row, mapping, "asin")).upper()
    inv = re.sub(r"\s+", "", _clean_cell(_cell_raw(row, mapping, "vendor_invoice_no")))
    po = _clean_code(_cell_raw(row, mapping, "purchase_order_no"))
    has_asin = bool(asin) and (
        ASIN_RE.match(asin) or (asin.startswith("B0") and len(asin) >= 4)
    )
    has_inv = bool(re.search(r"(?:ETD|CKD)/", inv, re.I))
    has_po = bool(po) and len(po) >= 4 and "/" not in po
    qty = _cell_float(_cell_raw(row, mapping, "quantity"))
    total = _cell_float(_cell_raw(row, mapping, "total_amount"))
    rate = _cell_float(_cell_raw(row, mapping, "rate"))

    if has_asin and (has_inv or has_po):
        return True
    if has_asin and (abs(total) >= 0.01 or qty > 0 or abs(rate) >= 0.01):
        return True
    return False


def is_page_continuation_row(row: list[str], mapping: dict[str, int]) -> bool:
    """True when a table row is the tail half of a line item split at a page break."""
    if is_table_footer_row(row, mapping):
        return False
    if row_serial_number(row, mapping):
        return False
    if is_complete_row_without_serial(row, mapping):
        return False
    desc = row_description(row, mapping)
    if desc and not is_summary_row(desc):
        return True
    return _row_has_continuation_identifiers(row, mapping)


def has_complete_line_totals(item: LineItem) -> bool:
    return abs(item.total_amount) >= 0.01 and 0 < item.quantity <= MAX_PLAUSIBLE_QTY


def has_valid_asin(item: LineItem) -> bool:
    return bool(ASIN_RE.match(item.asin or ""))


def has_complete_hsn(item: LineItem) -> bool:
    digits = re.sub(r"\D", "", item.hsn or "")
    return len(digits) >= 6


def looks_like_gstin_fragment(value: str) -> bool:
    """Partial or full GSTIN printed in the UPC/EAN column (Clicktech page-2 tails)."""
    code = _clean_code(value).upper()
    if not code:
        return False
    if GSTIN_FULL_RE.match(code):
        return True
    return bool(re.match(r"^\d{2}[A-Z]{4,8}\d{0,4}$", code)) and len(code) >= 8


def has_corrupted_numerics(item: LineItem) -> bool:
    if item.quantity > MAX_PLAUSIBLE_QTY:
        return True
    tax = (item.tax_type or "").strip().upper()
    if tax in {"0", "O"} or (tax.isdigit() and tax not in {"0"}):
        return True
    if (
        item.product
        and len(item.product) > 30
        and 0 < item.total_amount < 50
        and item.tax_amount == 0
        and item.quantity <= 1
    ):
        return True
    return False


def item_is_incomplete(item: LineItem) -> bool:
    """True when a parsed row still needs its page-2 tail to be complete."""
    asin = _clean_code(item.asin or "").upper()
    if asin and asin.startswith("B0") and not ASIN_RE.match(asin):
        return True
    hsn_digits = re.sub(r"\D", "", item.hsn or "")
    if item.hsn and 0 < len(hsn_digits) < 6:
        return True
    if looks_like_gstin_fragment(item.ean or ""):
        return True
    inv = re.sub(r"\s+", "", item.invoice_no or "")
    if inv and inv.endswith(("/", "-")):
        return True
    date = (item.invoice_date or "").strip()
    if date.endswith("-"):
        return True
    return False


def continuation_complements_prev(prev: LineItem, cont: LineItem) -> bool:
    """True when *cont* fills missing identifiers or text on an incomplete *prev*."""
    if cont.product.strip() and (
        not prev.product.strip()
        or cont.product.strip() not in prev.product
        and prev.product.strip() not in cont.product.strip()
    ):
        return True
    if _resolve_asin(prev, cont) != _clean_code(prev.asin or "").upper():
        return True
    hsn = _merge_split_digits(prev.hsn, cont.hsn)
    if hsn and hsn != (prev.hsn or ""):
        return True
    for field in ("ean", "sku", "combo", "invoice_no", "return_id", "shipment_id", "units"):
        prev_val = getattr(prev, field, "") or ""
        cont_val = getattr(cont, field, "") or ""
        if cont_val and not prev_val:
            return True
        if cont_val and prev_val and cont_val not in prev_val and prev_val not in cont_val:
            return True
    if not (prev.units or "").strip() and (cont.units or "").strip():
        return True
    if prev.quantity <= 0 and cont.quantity > 0:
        return True
    if abs(prev.total_amount) < 0.01 and abs(cont.total_amount) >= 0.01:
        return True
    if abs(prev.cost_per_unit) < 0.01 and abs(cont.cost_per_unit) >= 0.01:
        return True
    if not (prev.tax_type or "").strip() and (cont.tax_type or "").strip():
        return True
    return False


def looks_like_new_item(item: LineItem) -> bool:
    """True when a parsed row is a genuine new line item, not a page-break tail."""
    if (item.system_ref_no or "").strip():
        return True

    if looks_like_gstin_fragment(item.ean or ""):
        return False

    asin = _clean_code(item.asin or "")
    if asin.startswith("B0") and len(asin) < 10:
        return False

    if has_valid_asin(item) and has_complete_line_totals(item) and not has_corrupted_numerics(item):
        return True

    # Tail rows have no serial number. Shifted columns can still parse HSN+totals+IGST,
    # which previously blocked merge — require a valid ASIN to treat as a new item.
    if (
        has_complete_hsn(item)
        and has_complete_line_totals(item)
        and (item.tax_type or "").strip().upper() in {"IGST", "CGST", "SGST"}
    ):
        return False

    return False


def sanitize_continuation_item(item: LineItem) -> LineItem:
    """Zero mis-aligned numeric junk on tail rows before merge."""
    updates: dict[str, Any] = {}
    if item.quantity > MAX_PLAUSIBLE_QTY:
        updates["quantity"] = 0.0
    if has_corrupted_numerics(item):
        if abs(item.total_amount) < 50:
            updates["total_amount"] = 0.0
        if abs(item.total_cost) < 50:
            updates["total_cost"] = 0.0
        if abs(item.tax_amount) < 0.01 or (item.tax_type or "").strip() in {"0", ""}:
            updates["tax_amount"] = 0.0
        if (item.tax_type or "").strip() in {"0", "O"}:
            updates["tax_type"] = ""
    return item.model_copy(update=updates) if updates else item


def should_merge_continuation(prev: LineItem, cont: LineItem, page_number: int) -> bool:
    """True when *cont* is the wrapped tail of *prev* split across a page break."""
    if is_summary_row(cont.product):
        return False
    if looks_like_new_item(cont):
        return False

    prev_page = (prev.source_ref.page if prev.source_ref else 0) or 0
    if page_number < prev_page:
        return False

    cont_is_tail = not (cont.system_ref_no or "").strip()
    if not cont_is_tail:
        return False

    if item_is_incomplete(prev) and continuation_complements_prev(prev, cont):
        return True

    if item_is_incomplete(prev) and cont_is_tail:
        return True

    if not cont.product.strip():
        has_id = any(
            len(_clean_code(getattr(cont, f, ""))) >= 3
            for f in ("asin", "ean", "sku", "hsn", "combo")
        )
        if not has_id:
            return False

    if has_complete_line_totals(prev):
        return True
    if has_corrupted_numerics(cont):
        return True
    if cont.product.strip() and not has_complete_line_totals(cont):
        return True
    if (prev.system_ref_no or "").strip() and cont.product.strip():
        return True

    return False


def _merge_split_digits(prev_val: str, cont_val: str) -> str:
    prev = re.sub(r"\D", "", prev_val or "")
    cont = re.sub(r"\D", "", cont_val or "")
    if not cont:
        return _clean_code(prev_val)
    if not prev:
        return cont
    if cont in prev or prev in cont:
        return prev if len(prev) >= len(cont) else cont
    if 2 <= len(prev) < 8 and 1 <= len(cont) <= 6:
        return prev + cont
    if 4 <= len(prev) < 8 and 2 <= len(cont) <= 4:
        return prev + cont
    return _clean_code(prev_val) or prev


def _merge_long_identifier(prev_val: str, cont_val: str) -> str:
    """Join split Return ID / Shipment ID preserving all digits."""
    prev = re.sub(r"\s+", "", prev_val or "")
    cont = re.sub(r"\s+", "", cont_val or "")
    if not cont:
        return prev
    if not prev:
        return cont
    if cont in prev or prev in cont:
        return prev if len(prev) >= len(cont) else cont
    return prev + cont


def _looks_like_asin_fragment(code: str) -> bool:
    c = _clean_code(code)
    if not c or len(c) < 2 or len(c) > 8:
        return False
    if c.isdigit():
        return False
    if looks_like_gstin_fragment(c):
        return False
    return bool(re.match(r"^[A-Z0-9]+$", c, re.I))


def _merge_asin_codes(prev_val: str, cont_val: str) -> str:
    prev = _clean_code(prev_val).upper()
    cont = _clean_code(cont_val).upper()
    if ASIN_RE.match(prev):
        return prev
    if ASIN_RE.match(cont):
        return cont
    if not prev:
        return cont
    if not cont:
        return prev
    if prev.startswith("B0") and len(prev) < 10:
        if cont.startswith("B0"):
            longer = cont if len(cont) > len(prev) else prev
            return longer if ASIN_RE.match(longer) else prev
        if re.match(r"^[A-Z0-9]+$", cont):
            combined = prev + cont
            if ASIN_RE.match(combined):
                return combined
            if combined.startswith("B0") and len(combined) <= 10:
                return combined
    return prev


def _asin_tail_candidates(cont: LineItem) -> list[str]:
    """Collect identifier fragments on tail rows that may complete a split ASIN."""
    seen: set[str] = set()
    candidates: list[str] = []
    for field in ("asin", "ean", "sku", "combo"):
        val = _clean_code(getattr(cont, field, "")).upper()
        if not val or val in seen or looks_like_gstin_fragment(val):
            continue
        if _looks_like_asin_fragment(val) or (
            not val.startswith("B0") and re.match(r"^[A-Z0-9]{2,7}$", val)
        ):
            seen.add(val)
            candidates.append(val)
    return candidates


def _resolve_asin(prev: LineItem, cont: LineItem) -> str:
    asin = _merge_asin_codes(prev.asin, cont.asin)
    if ASIN_RE.match(asin):
        return asin
    for tail in _asin_tail_candidates(cont):
        trial = _merge_asin_codes(asin or prev.asin, tail)
        if len(trial) > len(asin or prev.asin or ""):
            asin = trial
        if ASIN_RE.match(asin):
            break
    return asin


def _merge_date_fragment(prev_val: str, cont_val: str) -> str:
    prev = _clean_cell(prev_val)
    cont = _clean_cell(cont_val)
    if not cont:
        return prev
    if not prev:
        return cont
    if not prev.endswith("-"):
        return _merge_wrap_text(prev, cont, allow_merge=True)

    prev_compact = re.sub(r"\s+", "", prev).rstrip("-")
    cont_compact = re.sub(r"\s+", "", cont)
    if cont_compact and prev_compact and cont_compact[0] == prev_compact[-1]:
        cont_compact = cont_compact[1:].lstrip("-")
        return f"{prev_compact}-{cont_compact}" if cont_compact else f"{prev_compact}-"
    if cont_compact.startswith(prev_compact):
        tail = cont_compact[len(prev_compact) :].lstrip("-")
        return f"{prev_compact}-{tail}" if tail else f"{prev_compact}-"
    return f"{prev_compact}-{cont_compact}" if cont_compact else prev


def _merge_wrap_text(prev_val: str, cont_val: str, *, allow_merge: bool = True) -> str:
    prev = _clean_cell(prev_val)
    cont = _clean_cell(cont_val)
    if not allow_merge or not cont:
        return prev
    if not prev:
        return cont
    if cont in prev or prev in cont:
        return prev if len(prev) >= len(cont) else cont
    if prev.endswith("-") or prev.endswith("/") or len(prev) <= 3:
        combined = prev + cont
        if prev.endswith("-") or prev.endswith("/"):
            combined = re.sub(r"\s+", "", combined)
        else:
            combined = re.sub(r"\s+", " ", combined).strip()
        return combined
    return prev


def _vendor_invoice_suffix_len(value: str) -> int:
    val = re.sub(r"\s+", "", _clean_cell(value))
    if "/" not in val:
        return 0
    last = val.rsplit("/", 1)[-1]
    return len(last) if last.isdigit() else 0


def _vendor_invoice_looks_complete(value: str) -> bool:
    """True when vendor invoice no already has a full ETD/CKD/CTDF reference."""
    val = re.sub(r"\s+", "", _clean_cell(value))
    if not re.search(r"(?:ETD|CKD|CTDF)/", val, re.I):
        return False
    if re.match(r"(?i)ETD/DF/\d{2}-\d{2}/\d+$", val):
        return True
    if re.match(r"(?i)(?:ETD|CKD)/\d{2}-\d{2}/\d+$", val):
        # ETD/25-26/07 is a page-break head fragment; ETD/24-25/307 is valid.
        return _vendor_invoice_suffix_len(val) >= 3
    if re.match(r"(?i)CTDF/\d{2}-\d{2}/\d+$", val):
        return _vendor_invoice_suffix_len(val) >= 4
    return False


def _try_merge_invoice_digit_tail(head: str, tail: str) -> str:
    """Join trailing digits split across a page break: ETD/25-26/07 + 91 -> ETD/25-26/0791."""
    head_compact = re.sub(r"\s+", "", _clean_cell(head))
    tail_compact = re.sub(r"\s+", "", _clean_cell(tail)).replace(",", "")
    if not re.fullmatch(r"\d{1,3}", tail_compact):
        return ""
    if not re.match(r"^(?:ETD|CKD)/", head_compact, re.I):
        return ""
    match = re.search(r"/(\d+)$", head_compact)
    if not match or len(match.group(1)) > 2:
        return ""
    return head_compact + tail_compact


def _invoice_head_accepts_digit_tail(ven_head: str) -> bool:
    head = re.sub(r"\s+", "", _clean_cell(ven_head))
    if not re.match(r"^(?:ETD|CKD)/", head, re.I):
        return False
    match = re.search(r"/(\d+)$", head)
    return bool(match and len(match.group(1)) <= 2)


_DATE_MONTH_RE = re.compile(
    r"(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)", re.I
)


def _looks_like_month_date_fragment(value: str) -> bool:
    return bool(_DATE_MONTH_RE.search(_clean_cell(value)))


def _looks_like_etrade_invoice_tail_in_date_column(value: str) -> bool:
    """True when a page-2 tail shifted the invoice suffix into the date column."""
    val = re.sub(r"\s+", "", _clean_cell(value))
    if not val:
        return False
    # Tail of ETD/25-26/0403 shifted into date column appears as 5-26/0403.
    if re.match(r"^\d-\d{2}/\d{3,}$", val):
        return True
    if re.match(r"^\d-\d{2}-\d{2}/\d{3,}$", val):
        return True
    if re.match(r"^\d{2}-\d{2}/\d{3,}$", val):
        return True
    return False


def _looks_like_etrade_invoice_digit_tail_in_date_column(value: str, ven_head: str) -> bool:
    """True when page-2 shifted only the last invoice digits into the date column."""
    val = re.sub(r"\s+", "", _clean_cell(value))
    if not re.fullmatch(r"\d{1,3}", val):
        return False
    return _invoice_head_accepts_digit_tail(ven_head)


def _looks_like_po_fragment_in_invoice_column(value: str, po_head: str) -> bool:
    """Alphanumeric PO wrap fragment misplaced in the vendor invoice column."""
    code = _clean_code(value)
    if not code or len(code) > 12:
        return False
    if re.search(r"(?:ETD|CKD|CTDF)/", code, re.I):
        return False
    if re.search(r"\d{2}-\d{2}/", code):
        return False
    if not re.match(r"^[A-Z0-9]+$", code, re.I):
        return False
    return bool(_clean_code(po_head)) or len(code) <= 8


def _detect_etrade_invoice_column_shift(
    merged: list[str],
    tail: list[str],
    mapping: dict[str, int],
) -> dict[str, Any] | None:
    """Detect ETRADE page-2 rows where invoice/PO tails landed in adjacent columns."""
    ven_idx = mapping.get("vendor_invoice_no")
    date_idx = mapping.get("vendor_invoice_date")
    po_idx = mapping.get("purchase_order_no")
    if ven_idx is None or date_idx is None:
        return None

    ven_head = re.sub(r"\s+", "", _clean_cell(merged[ven_idx] if ven_idx < len(merged) else ""))
    if _vendor_invoice_looks_complete(ven_head):
        return None
    if not re.match(r"^(?:ETD|CKD)/", ven_head, re.I):
        return None

    ven_tail = tail[ven_idx] if ven_idx < len(tail) else ""
    date_tail = tail[date_idx] if date_idx < len(tail) else ""
    inv_tail = ""
    if _looks_like_etrade_invoice_tail_in_date_column(date_tail):
        inv_tail = date_tail
    elif _looks_like_etrade_invoice_digit_tail_in_date_column(date_tail, ven_head):
        inv_tail = date_tail
    if not inv_tail:
        return None

    po_head = merged[po_idx] if po_idx is not None and po_idx < len(merged) else ""
    po_fragment = (
        _clean_code(ven_tail)
        if _looks_like_po_fragment_in_invoice_column(ven_tail, po_head)
        else ""
    )

    skip: set[int] = {date_idx}
    if po_fragment:
        skip.add(ven_idx)

    real_date_tail = ""
    next_idx = date_idx + 1
    if next_idx < len(tail):
        nxt = tail[next_idx]
        if _looks_like_month_date_fragment(nxt):
            real_date_tail = nxt
            skip.add(next_idx)

    return {
        "invoice_tail": inv_tail,
        "po_fragment": po_fragment,
        "date_tail": real_date_tail,
        "skip_tail_indices": skip,
    }


def _looks_like_summary_amount_in_invoice_column(value: str) -> bool:
    """True when a tail cell in the invoice column is a tax/total/currency value, not an ID fragment."""
    raw = (value or "").strip()
    if not raw:
        return False
    if _cell_is_summary_label(raw):
        return True
    if raw.upper() in {"INR", "USD", "EUR"}:
        return True
    normalized = raw.replace(",", "")
    if re.search(r"\d\.\d", normalized):
        return True
    if "," in raw:
        return True
    return False


def _merge_vendor_invoice_code(head: str, tail: str) -> str:
    """Join vendor invoice cells without appending summary totals or tax amounts."""
    if _looks_like_summary_amount_in_invoice_column(tail):
        return re.sub(r"\s+", "", _clean_cell(head)) or head
    head_compact = re.sub(r"\s+", "", _clean_cell(head))
    tail_compact = re.sub(r"\s+", "", _clean_cell(tail)).replace(",", "")
    if not tail_compact:
        return head_compact or head
    if not head_compact:
        return tail_compact
    digit_merge = _try_merge_invoice_digit_tail(head_compact, tail_compact)
    if digit_merge:
        return digit_merge
    if _vendor_invoice_looks_complete(head_compact):
        if re.fullmatch(r"\d+(?:\.\d+)?", tail_compact):
            return head_compact
    return _merge_invoice_no_fragment(head, tail)


def _merge_invoice_no_fragment(prev_val: str, cont_val: str) -> str:
    prev = re.sub(r"\s+", "", _clean_cell(prev_val))
    cont = re.sub(r"\s+", "", _clean_cell(cont_val))
    if not cont:
        return prev
    if not prev:
        return cont
    if _looks_like_summary_amount_in_invoice_column(cont_val):
        return prev
    if cont in prev or prev in cont:
        return prev if len(prev) >= len(cont) else cont
    if _vendor_invoice_looks_complete(prev):
        return prev
    if prev.endswith(("/", "-")) or len(prev) <= 8:
        return prev + cont
    if prev[-1].isdigit() and cont[0].isdigit():
        return prev + cont
    return prev


def _merge_decimal_amount(prev: float, cont: float) -> float | None:
    """Join split decimal tails: 2467.6 + 4 -> 2467.64, 2091.2 + 2 -> 2091.22."""
    if cont <= 0 or cont >= 100 or cont != int(cont):
        return None
    cont_int = int(cont)
    if abs(round(prev, 1) - prev) > 0.001:
        return None
    trial = round(prev + cont_int / 100, 2)
    return trial if trial > prev else None


def _merge_split_code(prev_val: str, cont_val: str) -> str:
    prev = _clean_code(prev_val)
    cont = _clean_code(cont_val)
    if not cont:
        return prev
    if not prev:
        return cont
    if cont in prev or prev in cont:
        if len(cont) <= 2:
            # "I" matches inside "DROPSHIP" — only skip when the value already ends with it.
            if prev.endswith(cont):
                return prev
        else:
            return prev if len(prev) >= len(cont) else cont
    return prev + cont


def _merge_identifier_fields(prev: LineItem, cont: LineItem) -> dict[str, Any]:
    updates: dict[str, Any] = {}

    hsn = _merge_split_digits(prev.hsn, cont.hsn)
    if hsn and hsn != (prev.hsn or ""):
        updates["hsn"] = hsn

    asin = _resolve_asin(prev, cont)
    ean_consumed = ""
    cont_ean = _clean_code(cont.ean)
    if not ASIN_RE.match(asin) and _clean_code(prev.asin).startswith("B0"):
        if _looks_like_asin_fragment(cont_ean):
            trial = _merge_asin_codes(prev.asin, cont_ean)
            if len(trial) > len(asin or prev.asin or ""):
                asin = trial
            if ASIN_RE.match(asin):
                ean_consumed = cont_ean
    if asin and asin != (prev.asin or ""):
        updates["asin"] = asin

    if ASIN_RE.match(asin):
        cont_ean_clean = _clean_code(cont.ean or "")
        prev_ean = _clean_code(prev.ean or "")
        if cont_ean_clean and cont_ean_clean in asin:
            updates["ean"] = prev_ean if prev_ean and prev_ean not in asin else ""
        elif ean_consumed:
            updates["ean"] = prev_ean if prev_ean and prev_ean not in asin else ""

    for field in ("ean", "sku", "combo"):
        if field == "ean" and field in updates:
            continue
        raw = getattr(cont, field, "")
        if field == "ean" and (ean_consumed or looks_like_gstin_fragment(raw)):
            cont_val = ""
        else:
            cont_val = raw
        merged = _merge_split_code(getattr(prev, field, ""), cont_val)
        if merged and merged != getattr(prev, field, ""):
            if field == "ean" and looks_like_gstin_fragment(merged):
                updates["ean"] = ""
            else:
                updates[field] = merged

    merged_date = _merge_date_fragment(prev.invoice_date or "", cont.invoice_date or "")
    if merged_date and merged_date != (prev.invoice_date or ""):
        updates["invoice_date"] = merged_date

    prev_inv = prev.invoice_no or ""
    cont_inv = cont.invoice_no or ""
    redirect = _po_wrap_tail_from_wrong_column(prev.combo or "", prev_inv, cont_inv)
    if redirect:
        merged_po = _merge_split_code(prev.combo or "", redirect)
        if merged_po and merged_po != (prev.combo or ""):
            updates["combo"] = merged_po
        cont_inv = "" if _clean_code(cont_inv) == redirect else cont_inv
    merged_inv = _merge_invoice_no_fragment(prev_inv, cont_inv)
    if merged_inv and merged_inv != prev_inv:
        updates["invoice_no"] = merged_inv

    for field in ("return_id", "shipment_id"):
        merged = _merge_long_identifier(getattr(prev, field, ""), getattr(cont, field, ""))
        if merged and merged != getattr(prev, field, ""):
            updates[field] = merged

    if cont.units and not prev.units:
        updates["units"] = cont.units

    return updates


def _maybe_fix_rate_from_net(rate: float, net: float, qty: float) -> float | None:
    """Recover rate when the head row total/net is correct but rate was truncated at page break."""
    if qty <= 0 or net <= 0:
        return None
    implied = round(net / qty, 2)
    if rate <= 0:
        return implied
    if implied > rate * 1.5 and abs(implied - rate) > max(1.0, rate * 0.05):
        return implied
    return None


def _merge_rate_fragments(prev_rate: float, cont_rate: float) -> float | None:
    """Join rate fragments such as 209 (page 1) + 1.22 (page 2) -> 2091.22."""
    if prev_rate <= 0 or cont_rate <= 0 or cont_rate >= 100:
        return None
    prev_whole = int(round(prev_rate))
    if cont_rate < 10 and abs(cont_rate - round(cont_rate, 2)) < 0.001:
        dec = f"{cont_rate:.2f}".split(".")[1]
        if len(dec) == 2:
            trial = float(f"{prev_whole}.{dec}")
            if trial > prev_rate:
                return trial
        combined = float(f"{prev_whole}{int(round(cont_rate * 100)):02d}")
        if combined > prev_rate * 5:
            return round(combined / 100, 2) if combined > prev_rate * 50 else combined
    return None


def _merge_numeric_fields(prev: LineItem, cont: LineItem) -> dict[str, Any]:
    """Merge qty / price / tax / total from tail row without overwriting good head values."""
    updates: dict[str, Any] = {}
    prev_complete = has_complete_line_totals(prev)
    cont_sanitized = sanitize_continuation_item(cont)
    cont_trusted = (
        has_complete_line_totals(cont_sanitized)
        and not has_corrupted_numerics(cont_sanitized)
        and abs(cont_sanitized.total_amount) >= max(abs(prev.total_amount), 50)
    )

    if prev_complete and not cont_trusted:
        fixed_rate = _maybe_fix_rate_from_net(prev.cost_per_unit, prev.total_cost, prev.quantity)
        if fixed_rate is not None:
            updates["cost_per_unit"] = fixed_rate
        elif cont_sanitized.cost_per_unit > 0:
            frag_rate = _merge_rate_fragments(prev.cost_per_unit, cont_sanitized.cost_per_unit)
            if frag_rate is not None:
                updates["cost_per_unit"] = frag_rate

        merged_total = _merge_decimal_amount(prev.total_amount, cont_sanitized.total_amount)
        if merged_total is not None:
            updates["total_amount"] = merged_total

        merged_net = _merge_decimal_amount(prev.total_cost, cont_sanitized.total_cost)
        if merged_net is not None:
            updates["total_cost"] = merged_net

        return updates

    prev_incomplete = abs(prev.total_amount) < 0.01 and prev.quantity > 0

    if prev_incomplete and abs(cont_sanitized.total_amount) >= 0.01:
        if abs(cont_sanitized.total_amount) >= abs(prev.total_amount):
            updates["total_amount"] = cont_sanitized.total_amount
        if abs(cont_sanitized.total_cost) >= 0.01:
            updates["total_cost"] = cont_sanitized.total_cost
        if abs(cont_sanitized.tax_amount) >= 0.01:
            updates["tax_amount"] = cont_sanitized.tax_amount
        if abs(cont_sanitized.cost_per_unit) >= 0.01:
            updates["cost_per_unit"] = cont_sanitized.cost_per_unit
        if cont_sanitized.tax_rate:
            updates["tax_rate"] = cont_sanitized.tax_rate
        if cont_sanitized.tax_type:
            updates["tax_type"] = cont_sanitized.tax_type
        if prev.total_amount <= 0 < cont_sanitized.total_amount:
            updates["total_amount"] = -abs(cont_sanitized.total_amount)
            if cont_sanitized.total_cost > 0:
                updates["total_cost"] = -abs(cont_sanitized.total_cost)
    elif not prev_complete and cont_trusted:
        updates["total_amount"] = cont_sanitized.total_amount
        if abs(cont_sanitized.total_cost) >= 0.01:
            updates["total_cost"] = cont_sanitized.total_cost
        if abs(cont_sanitized.tax_amount) >= 0.01:
            updates["tax_amount"] = cont_sanitized.tax_amount
        if abs(cont_sanitized.cost_per_unit) >= 0.01:
            updates["cost_per_unit"] = cont_sanitized.cost_per_unit
        if 0 < cont_sanitized.quantity <= MAX_PLAUSIBLE_QTY:
            updates["quantity"] = cont_sanitized.quantity
        if cont_sanitized.tax_rate:
            updates["tax_rate"] = cont_sanitized.tax_rate
        if cont_sanitized.tax_type:
            updates["tax_type"] = cont_sanitized.tax_type
    elif not prev_complete:
        for field in ("quantity", "cost_per_unit", "total_cost", "tax_amount", "tax_rate"):
            pv = float(getattr(prev, field) or 0)
            cv = float(getattr(cont_sanitized, field) or 0)
            if abs(pv) < 0.01 and abs(cv) >= 0.01:
                if field == "quantity" and cv > MAX_PLAUSIBLE_QTY:
                    continue
                updates[field] = cv
        if cont_sanitized.tax_type and not (prev.tax_type or "").strip():
            updates["tax_type"] = cont_sanitized.tax_type
        if abs(prev.total_amount) < 0.01 and abs(cont_sanitized.total_amount) >= 0.01:
            if not has_corrupted_numerics(cont_sanitized):
                updates["total_amount"] = cont_sanitized.total_amount

    return updates


def _merge_raw_text_cell(head: str, tail: str) -> str:
    head = _clean_cell(head)
    tail = _clean_cell(tail)
    if not tail:
        return head
    if not head:
        return tail
    if tail.lower() in head.lower():
        return head
    if head.lower() in tail.lower():
        return tail
    return f"{head} {tail}".strip()


def _merge_raw_code_cell(field: str, head: str, tail: str) -> str:
    if field == "vendor_invoice_no":
        return _merge_vendor_invoice_code(head, tail)
    if field == "hsn":
        merged = _merge_split_digits(head, tail)
        return merged or _merge_split_code(head, tail)
    if field == "asin":
        head_c = _clean_code(head).upper()
        tail_c = _clean_code(tail).upper()
        if head_c.startswith("B0") and tail_c and not ASIN_RE.match(head_c):
            trial = _merge_asin_codes(head, tail_c if _looks_like_asin_fragment(tail_c) else tail)
            if ASIN_RE.match(trial):
                return trial
        return _merge_split_code(head, tail).upper() if field == "asin" else _merge_split_code(head, tail)
    return _merge_split_code(head, tail)


def _merge_raw_numeric_cell(field: str, head: str, tail: str) -> str:
    hf = _cell_float(head)
    tf = _cell_float(tail)
    if hf != 0 and tf == 0:
        return head
    if hf == 0 and tf != 0:
        return tail
    if field == "rate":
        frag = _merge_rate_fragments(hf, tf)
        if frag is not None:
            return str(frag)
    # Quantity is always a whole number on Clicktech invoices; do not join a footer
    # total like 41 onto qty 1 as 1.41 (decimal tail merge is for split amounts only).
    if field == "quantity":
        if hf != 0 and abs(hf - round(hf)) < 0.001:
            return head
        return tail if tf != 0 else head
    merged = _merge_decimal_amount(hf, tf)
    if merged is not None:
        return str(merged)
    return head if hf != 0 else tail


def _merge_raw_cell(field: str, head: str, tail: str) -> str:
    """Join one table column across a page-break head row and tail row."""
    head = (head or "").strip()
    tail = (tail or "").strip()
    if not tail:
        return head
    if not head:
        return tail
    if field == "sl_no":
        return head
    if field == "description":
        return _merge_raw_text_cell(head, tail)
    if field in BOX_MERGE_CODE_FIELDS:
        return _merge_raw_code_cell(field, head, tail)
    if field == "vendor_invoice_date":
        return _merge_date_fragment(head, tail)
    if field in BOX_MERGE_NUMERIC_FIELDS:
        return _merge_raw_numeric_cell(field, head, tail)
    if field in {"unit_code", "tax_type"}:
        return head or tail
    return head or tail


def merge_continuation_rows(
    head_row: list[str],
    tail_row: list[str],
    mapping: dict[str, int],
) -> list[str]:
    """Merge a page-break tail row into the previous head row, column by column.

    When box 1 (Sl. No.) is empty on page 2, each of the ~17 columns is joined
    independently: empty tail cell → keep head; empty head → take tail; both
    filled → join fragments (description text, split ASIN/HSN/invoice, etc.).
    """
    expected = expected_column_count(mapping)
    if expected <= 0:
        return list(head_row)

    head = normalize_table_row(head_row, mapping, continuation=False)
    tail = normalize_table_row(tail_row, mapping, continuation=True)
    if is_table_footer_row(tail, mapping):
        merged = list(head)
        while len(merged) < expected:
            merged.append("")
        return merged[:expected]

    merged = list(head)
    while len(merged) < expected:
        merged.append("")
    merged = merged[:expected]

    po_idx = mapping.get("purchase_order_no")
    ven_idx = mapping.get("vendor_invoice_no")
    redirect_po_tail = ""
    if po_idx is not None and ven_idx is not None:
        po_head = merged[po_idx] if po_idx < len(merged) else ""
        ven_head = merged[ven_idx] if ven_idx < len(merged) else ""
        ven_tail = tail[ven_idx] if ven_idx < len(tail) else ""
        redirect_po_tail = _po_wrap_tail_from_wrong_column(po_head, ven_head, ven_tail)

    shift = _detect_etrade_invoice_column_shift(merged, tail, mapping)
    premerged_ven = False
    shift_date_tail = ""
    skip_tail_indices: set[int] = set()
    if shift:
        if ven_idx is not None:
            merged[ven_idx] = _merge_vendor_invoice_code(
                merged[ven_idx],
                shift["invoice_tail"],
            )
            premerged_ven = True
        if shift.get("po_fragment") and po_idx is not None:
            merged[po_idx] = _merge_split_code(
                merged[po_idx] if po_idx < len(merged) else "",
                shift["po_fragment"],
            )
        shift_date_tail = shift.get("date_tail", "")
        skip_tail_indices = set(shift.get("skip_tail_indices", set()))

    for field, idx in mapping.items():
        if idx >= expected:
            continue
        if premerged_ven and field == "vendor_invoice_no":
            continue
        head_cell = merged[idx] if idx < len(merged) else ""
        tail_cell = tail[idx] if idx < len(tail) else ""
        if field == "vendor_invoice_date" and shift_date_tail:
            tail_cell = shift_date_tail
        elif idx in skip_tail_indices:
            tail_cell = ""
        if redirect_po_tail:
            if field == "vendor_invoice_no" and _clean_code(tail_cell) == redirect_po_tail:
                tail_cell = ""
            if field == "purchase_order_no" and not (tail_cell or "").strip():
                tail_cell = redirect_po_tail
        merged[idx] = _merge_raw_cell(field, head_cell, tail_cell)

    return merged


def merge_line_item_continuation(prev: LineItem, cont: LineItem) -> LineItem:
    """Merge head + tail of a line item split across a page break."""
    cont = sanitize_continuation_item(cont)

    prev_product = prev.product.strip()
    cont_product = cont.product.strip()
    if cont_product:
        merged = f"{prev_product} {cont_product}".strip() if prev_product else cont_product
    else:
        merged = prev_product

    updates: dict[str, Any] = {"product": _clean_product(merged)}
    updates.update(_merge_identifier_fields(prev, cont))
    updates.update(_merge_numeric_fields(prev, cont))

    merged_item = prev.model_copy(update=updates)
    fixed_rate = _maybe_fix_rate_from_net(
        merged_item.cost_per_unit, merged_item.total_cost, merged_item.quantity
    )
    if fixed_rate is not None and fixed_rate != merged_item.cost_per_unit:
        merged_item = merged_item.model_copy(update={"cost_per_unit": fixed_rate})
    if merged_item.total_cost > 0 and merged_item.quantity > 0:
        net_rate = round(merged_item.total_cost / merged_item.quantity, 2)
        if abs(merged_item.cost_per_unit - net_rate) > 0.015:
            merged_item = merged_item.model_copy(update={"cost_per_unit": net_rate})
    return merged_item


def row_is_description_only_continuation(row: list[str], mapping: dict[str, int]) -> bool:
    if not is_page_continuation_row(row, mapping):
        return False

    for field in ("quantity", "rate", "taxable_value", "total_amount", "tax_amount"):
        idx = mapping.get(field)
        if idx is not None and idx < len(row) and _cell_float(row[idx]) != 0:
            return False
    return True


def _cell_float(value: str) -> float:
    cleaned = re.sub(r"\s+", "", value or "").replace(",", "")
    if not cleaned:
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
        return float(match.group()) if match else 0.0


def _id_digit_len(value: str) -> int:
    return len(re.sub(r"\D", "", value or ""))


def _should_merge_id_tail(prev_val: str, cont_val: str) -> bool:
    prev = re.sub(r"\D", "", prev_val or "")
    cont = re.sub(r"\D", "", cont_val or "")
    if not prev or not cont:
        return False
    if cont in prev or prev in cont:
        return True
    combined = len(prev) + len(cont)
    if combined in (15, 18) and len(cont) >= 5:
        return True
    if len(prev) <= 9 and len(cont) >= 4:
        return True
    return False


def _merge_id_tail(prev_val: str, cont_val: str) -> str:
    if not _should_merge_id_tail(prev_val, cont_val):
        return prev_val or ""
    return _merge_long_identifier(prev_val, cont_val)


def _recover_trailing_amount(row: list[str]) -> float:
    best = 0.0
    for cell in row[-8:]:
        val = _cell_float(cell)
        if abs(val) >= abs(best) and abs(val) >= 1:
            best = val
    return best


def _apply_credit_sign(prev: LineItem, value: float) -> float:
    if value == 0:
        return value
    if prev.tax_amount < 0 or prev.total_amount < 0 or prev.total_cost < 0:
        return -abs(value)
    return value


def build_shifted_continuation_item(
    row: list[str],
    mapping: dict[str, int],
    page_number: int,
    prev: LineItem,
) -> LineItem | None:
    """Build a continuation item when tail fragments landed in the wrong columns."""
    if not is_page_continuation_row(row, mapping):
        return None

    desc_idx = mapping.get("description")
    product = row_description(row, mapping)

    asin = _clean_code(_cell_raw(row, mapping, "asin")).upper()
    ean = _clean_code(_cell_raw(row, mapping, "ean"))
    hsn = _clean_code(_cell_raw(row, mapping, "hsn"))
    combo = _clean_code(_cell_raw(row, mapping, "purchase_order_no"))
    invoice_no = re.sub(r"\s+", "", _clean_cell(_cell_raw(row, mapping, "vendor_invoice_no")))
    invoice_date = _clean_cell(_cell_raw(row, mapping, "vendor_invoice_date"))
    return_id = _clean_code(_cell_raw(row, mapping, "return_id"))
    shipment_id = _clean_code(_cell_raw(row, mapping, "shipment_id"))
    units = _clean_cell(_cell_raw(row, mapping, "unit_code"))

    prev_asin = _clean_code(prev.asin or "").upper()
    need_asin = bool(prev_asin and not ASIN_RE.match(prev_asin))

    for idx, raw in enumerate(row):
        if desc_idx is not None and idx == desc_idx:
            continue
        cell = (raw or "").strip()
        if not cell:
            continue
        code = _clean_code(cell).upper()

        if need_asin and code and len(code) <= 7 and re.match(r"^[A-Z0-9]+$", code):
            trial = _merge_asin_codes(prev_asin or asin, code)
            if len(trial) > len(asin or prev_asin or ""):
                asin = trial
            if ASIN_RE.match(asin or trial):
                need_asin = False
            continue

        digits = re.sub(r"\D", "", cell)
        if digits:
            for field, current, prev_val in (
                ("return_id", return_id, prev.return_id or ""),
                ("shipment_id", shipment_id, prev.shipment_id or ""),
            ):
                base = current or prev_val
                if _should_merge_id_tail(base, digits):
                    trial = _merge_id_tail(base, digits)
                    if _id_digit_len(trial) > _id_digit_len(current or prev_val):
                        if field == "return_id":
                            return_id = trial
                        else:
                            shipment_id = trial

        if "/" in cell and len(re.sub(r"\s+", "", cell)) >= 6:
            trial = _merge_invoice_no_fragment(invoice_no or prev.invoice_no or "", cell)
            if len(trial) > len(invoice_no or ""):
                invoice_no = trial
        elif invoice_no and len(invoice_no) <= 14:
            if _po_wrap_tail_from_wrong_column(
                combo or prev.combo or "",
                invoice_no or prev.invoice_no or "",
                cell,
            ):
                trial_po = _merge_split_code(combo or prev.combo or "", _clean_code(cell))
                if trial_po:
                    combo = trial_po
            else:
                trial = _merge_invoice_no_fragment(invoice_no, cell)
                if len(trial) > len(invoice_no):
                    invoice_no = trial

        if re.search(r"[A-Z]{3}-\d", cell, re.I):
            trial = _merge_date_fragment(invoice_date or prev.invoice_date or "", cell)
            if trial and len(trial) >= len(invoice_date or ""):
                invoice_date = trial

        if not combo and _clean_code(cell) and 4 <= len(_clean_code(cell)) <= 12:
            if not code.isdigit() and not ASIN_RE.match(code) and not looks_like_gstin_fragment(code):
                combo = _clean_code(cell)

    quantity = _cell_float(_cell_raw(row, mapping, "quantity"))
    rate = _cell_float(_cell_raw(row, mapping, "rate"))
    taxable_value = _cell_float(_cell_raw(row, mapping, "taxable_value"))
    tax_amount = _cell_float(_cell_raw(row, mapping, "tax_amount"))
    total_amount = _cell_float(_cell_raw(row, mapping, "total_amount"))
    tax_rate = _cell_float(_cell_raw(row, mapping, "tax_rate"))
    tax_type = _clean_cell(_cell_raw(row, mapping, "tax_type"))

    if abs(total_amount) < 0.01:
        idx = mapping.get("total_amount")
        if idx is not None and idx < len(row):
            total_amount = _cell_float(row[idx])
        if abs(total_amount) < 0.01:
            total_amount = _recover_trailing_amount(row)
    if abs(taxable_value) < 0.01:
        idx = mapping.get("taxable_value")
        if idx is not None and idx < len(row):
            taxable_value = _cell_float(row[idx])
        if abs(taxable_value) < 0.01 and abs(total_amount) >= 0.01:
            taxable_value = round(total_amount / 1.05, 2) if total_amount else 0.0
    if abs(tax_amount) < 0.01 and abs(taxable_value) >= 0.01 and abs(total_amount) >= 0.01:
        tax_amount = round(abs(total_amount) - abs(taxable_value), 2)
        if prev.tax_amount < 0 or prev.total_amount < 0:
            tax_amount = -abs(tax_amount)

    total_amount = _apply_credit_sign(prev, total_amount)
    taxable_value = _apply_credit_sign(prev, taxable_value)
    if rate > 0 and (prev.total_amount < 0 or prev.tax_amount < 0):
        rate = -abs(rate)

    has_data = any(
        [
            product,
            asin,
            ean,
            hsn,
            combo,
            return_id,
            shipment_id,
            invoice_no,
            invoice_date,
            units,
            quantity > 0,
            rate > 0,
            abs(taxable_value) >= 0.01,
            abs(total_amount) >= 0.01,
        ]
    )
    if not has_data:
        return None

    return LineItem(
        product=product,
        asin=asin,
        ean=ean,
        hsn=hsn,
        combo=combo,
        invoice_no=invoice_no,
        invoice_date=invoice_date,
        return_id=return_id,
        shipment_id=shipment_id,
        units=units,
        quantity=quantity,
        cost_per_unit=rate,
        total_cost=taxable_value,
        tax_rate=tax_rate,
        tax_type=tax_type,
        tax_amount=tax_amount,
        total_amount=total_amount,
        source_ref={"page": page_number, "confidence": 0.75},
    )


def try_merge_description_only_row(
    items: list[LineItem],
    row: list[str],
    mapping: dict[str, int],
    page_number: int,
) -> bool:
    if not items or not is_page_continuation_row(row, mapping):
        return False
    # Rows with identifier or numeric cells must use the full parse + merge path
    # so ASIN/HSN/EAN/PO/price tails are not dropped.
    if _row_has_identifier_or_numeric_cells(row, mapping):
        return False
    if not row_is_description_only_continuation(row, mapping):
        return False

    desc = row_description(row, mapping)
    prev = items[-1]
    prev_page = (prev.source_ref.page if prev.source_ref else 0) or 0
    if page_number < prev_page:
        return False

    cont = LineItem(product=desc, source_ref={"page": page_number, "confidence": 0.8})
    items[-1] = merge_line_item_continuation(prev, cont)
    return True


def consolidate_page_break_items(items: list[LineItem], full_text: str) -> list[LineItem]:
    """Final pass: merge any remaining orphan tails, then drop page-2 reprints."""
    consolidated: list[LineItem] = []
    for item in items:
        page_number = (item.source_ref.page if item.source_ref else 0) or 0
        if consolidated and should_merge_continuation(consolidated[-1], item, page_number):
            consolidated[-1] = merge_line_item_continuation(consolidated[-1], item)
            continue
        consolidated.append(item)
    return dedupe_reprinted_line_items(consolidated)


def business_fingerprint(item: LineItem) -> tuple[Any, ...]:
    return (
        _clean_code(item.asin or ""),
        _clean_code(item.combo or ""),
        re.sub(r"\s+", "", item.invoice_no or ""),
        round(item.total_amount, 2),
        round(item.quantity, 2),
    )


def reprint_match_key(item: LineItem) -> tuple[Any, ...]:
    """Match keys for page-2 reprint detection (includes Sl. No. so legit repeats stay)."""
    inv = _strip_summary_suffix(re.sub(r"\s+", "", item.invoice_no or ""))
    return (
        (item.system_ref_no or "").strip(),
        _clean_code(item.asin or ""),
        inv,
        round(item.total_amount, 2),
        round(item.quantity, 2),
        (item.product or "").strip().lower()[:50],
    )


_VENDOR_INVOICE_STRIP_RE = re.compile(
    r"(?i)(?:ETD/DF/\d{2}-\d{2}/\d+|(?:ETD|CKD|CTDF)/\d{2}-\d{2}/\d+)"
)


def _strip_summary_suffix(value: str) -> str:
    """Remove summary/footer text accidentally merged into a code cell."""
    val = re.sub(r"\s+", "", value or "")
    match = _VENDOR_INVOICE_STRIP_RE.match(val)
    if match:
        return match.group(0)
    val = re.sub(r"(?i)(subtotal|totalqty|currency|grandtotal|forigst|forcgst).*$", "", val)
    return val.strip()


def _po_wrap_tail_from_wrong_column(po_head: str, ven_head: str, ven_tail: str) -> str:
    """Return *ven_tail* when a page-break shift put a PO wrap fragment in the invoice column."""
    tail = _clean_code(ven_tail)
    if not tail or len(tail) > 3:
        return ""
    if not re.match(r"^[A-Z]+$", tail, re.I):
        return ""
    if not _vendor_invoice_looks_complete(ven_head):
        return ""
    po = _clean_code(po_head)
    if not po:
        return ""
    if po.endswith("-") or re.search(r"(?:FOU|FO|HIP|OPS|DR|PO)$", po, re.I):
        return tail
    return ""


def _clean_po_code(value: str) -> str:
    code = _clean_code(value)
    code = re.sub(r"(?i)(totalqty|currency|subtotal|grandtotal).*$", "", code)
    if re.match(r"^DR", code, re.I):
        match = re.match(r"^[A-Z0-9]+(?:-[A-Z0-9]+)*", code, re.I)
        return match.group(0).upper() if match else code
    match = re.match(r"^[A-Z0-9]{4,12}", code, re.I)
    return match.group(0).upper() if match else code


def is_summary_polluted_line_item(item: LineItem) -> bool:
    """Reject summary/footer rows that leaked into a line-item slot."""
    if is_summary_row(item.product or ""):
        return True
    if abs(item.total_amount) >= 0.01 and (item.asin or item.product):
        # Valid amounts + product — keep row even if PO/invoice cell has trailing junk.
        return False
    for val in (item.combo, item.product, item.invoice_no, item.hsn):
        if not val:
            continue
        compact = re.sub(r"[^a-z0-9]", "", val.lower())
        if any(marker in compact for marker in SUMMARY_POLLUTION_MARKERS):
            return True
    return False


def is_duplicate_serial_number(items: list[LineItem], candidate: LineItem) -> bool:
    """Drop a second full row with the same Sl. No. already extracted."""
    sl = (candidate.system_ref_no or "").strip()
    if not sl or not items:
        return False
    for existing in items:
        if (existing.system_ref_no or "").strip() != sl:
            continue
        if has_complete_line_totals(existing):
            return True
    return False


def is_immediate_reprint_duplicate(
    items: list[LineItem],
    candidate: LineItem,
    page_number: int,
) -> bool:
    """Drop page-2+ rows that repeat the line item we just finished merging."""
    if not items or not has_complete_line_totals(candidate):
        return False
    prev = items[-1]
    prev_page = (prev.source_ref.page if prev.source_ref else 0) or 0
    if page_number <= prev_page:
        return False
    if reprint_match_key(prev) != reprint_match_key(candidate):
        return False
    cand_sl = (candidate.system_ref_no or "").strip()
    prev_sl = (prev.system_ref_no or "").strip()
    if cand_sl and prev_sl and cand_sl != prev_sl:
        return False
    return True


def is_page2_reprint_duplicate(
    items: list[LineItem],
    candidate: LineItem,
    page_number: int,
) -> bool:
    """Drop page-2+ full rows that repeat an already-complete page-1 line (split-row reprint)."""
    if page_number <= 1 or not items or not candidate.asin:
        return False
    if not has_complete_line_totals(candidate):
        return False

    cand_sl = (candidate.system_ref_no or "").strip()
    fp = reprint_match_key(candidate)
    page1_matches = [
        it
        for it in items
        if reprint_match_key(it) == fp
        and ((it.source_ref.page if it.source_ref else 0) or 0) <= 1
        and has_complete_line_totals(it)
    ]
    if not page1_matches:
        return False

    # Same Sl. No. on page 1 and page 2 → reprint, not a new line.
    if cand_sl:
        return any((it.system_ref_no or "").strip() == cand_sl for it in page1_matches)

    # Empty Sl. No. on page 2: only drop when exactly one page-1 twin exists.
    if len(page1_matches) != 1:
        return False

    has_other_product = any(
        reprint_match_key(it) != fp and (it.product or "").strip() for it in items
    )
    if not has_other_product:
        return False

    return True


def dedupe_reprinted_line_items(items: list[LineItem]) -> list[LineItem]:
    """Remove summary pollution and page-2 reprints of page-1 rows."""
    result: list[LineItem] = []
    for item in items:
        if is_summary_polluted_line_item(item):
            continue
        page_number = (item.source_ref.page if item.source_ref else 0) or 0
        if is_duplicate_serial_number(result, item):
            continue
        if is_immediate_reprint_duplicate(result, item, page_number):
            continue
        if is_page2_reprint_duplicate(result, item, page_number):
            continue
        result.append(item)
    return result


def apply_page_break_merge(
    items: list[LineItem],
    row: list[str],
    mapping: dict[str, int],
    page_number: int,
    new_item: LineItem,
) -> bool:
    """If *new_item* is a continuation tail, merge into previous item. Returns True if merged."""
    if not items:
        return False
    cont = sanitize_continuation_item(new_item)
    if should_merge_continuation(items[-1], cont, page_number):
        items[-1] = merge_line_item_continuation(items[-1], cont)
        return True
    if is_page_continuation_row(row, mapping) and should_merge_continuation(items[-1], cont, page_number):
        items[-1] = merge_line_item_continuation(items[-1], cont)
        return True
    return False
