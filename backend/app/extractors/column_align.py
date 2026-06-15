"""Align table rows to the header column count (~17 cols) before field extraction.

Pdfplumber often emits page-break tail rows with extra empty columns or shifted
cells. We always normalize to the mapped column count and, for continuation
rows, re-score cell placement by content type (vendor invoice no, GST rate, etc.).
"""
from __future__ import annotations

import re
from itertools import combinations

ASIN_RE = re.compile(r"^B0[A-Z0-9]{8}$", re.I)
DATE_FRAG_RE = re.compile(r"[A-Z]{3}-\d{2}", re.I)
VENDOR_INV_RE = re.compile(r"(?:ETD|CKD)/", re.I)
UNIT_CODES = {"EACH", "PCS", "NOS", "UNIT", "KG", "BOX"}
TAX_TYPES = {"IGST", "CGST", "SGST", "CESS"}
VALID_TAX_RATES = {0.0, 5.0, 12.0, 18.0, 28.0}

# Fields ordered from most distinctive to least (for content reassignment).
FIELD_ASSIGN_ORDER = (
    "vendor_invoice_no",
    "tax_type",
    "vendor_invoice_date",
    "unit_code",
    "asin",
    "return_id",
    "shipment_id",
    "purchase_order_no",
    "hsn",
    "tax_rate",
    "quantity",
    "rate",
    "taxable_value",
    "tax_amount",
    "total_amount",
    "ean",
    "sku",
    "description",
    "sl_no",
)


def expected_column_count(mapping: dict[str, int]) -> int:
    if not mapping:
        return 0
    return max(mapping.values()) + 1


def _clean_code(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def _clean_cell(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("\n", " ")).strip()


def _to_float(value: str) -> float:
    cleaned = re.sub(r"\s+", "", value or "").replace(",", "")
    if not cleaned or cleaned in {"-", "—"}:
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
        return float(match.group()) if match else 0.0


def score_cell_for_field(field: str, value: str) -> float:
    v = _clean_cell(value)
    if not v:
        return 0.0

    if field == "sl_no":
        return 1.0 if re.fullmatch(r"\d+", _clean_code(v)) else 0.0

    if field == "description":
        if len(v) > 20:
            return 1.0
        if len(v) > 5 and not _to_float(v):
            return 0.7
        return 0.2

    if field == "hsn":
        digits = re.sub(r"\D", "", v)
        if 6 <= len(digits) <= 8:
            return 1.0
        if 3 <= len(digits) <= 5:
            return 0.5
        return 0.0

    if field == "asin":
        code = _clean_code(v).upper()
        if ASIN_RE.match(code):
            return 1.0
        if code.startswith("B0") and len(code) >= 4:
            return 0.75
        if re.match(r"^[A-Z0-9]{2,7}$", code):
            return 0.35
        return 0.0

    if field == "ean":
        code = _clean_code(v)
        if re.fullmatch(r"\d{8,14}", code):
            return 1.0
        if re.fullmatch(r"\d{2}[A-Z]{4,8}\d{0,4}[A-Z0-9]{0,3}", code, re.I):
            return 0.35
        return 0.0

    if field == "purchase_order_no":
        code = _clean_code(v)
        if "/" in code or VENDOR_INV_RE.search(code):
            return 0.0
        if 4 <= len(code) <= 12 and re.fullmatch(r"[A-Z0-9]+", code, re.I):
            return 1.0
        return 0.0

    if field == "vendor_invoice_no":
        code = re.sub(r"\s+", "", v)
        if VENDOR_INV_RE.search(code):
            return 1.0
        if "/" in code and re.search(r"\d", code) and len(code) >= 8:
            return 0.65
        return 0.0

    if field == "vendor_invoice_date":
        if DATE_FRAG_RE.search(v):
            return 1.0
        if re.search(r"\d{1,2}[-/]", v):
            return 0.45
        return 0.0

    if field in ("return_id", "shipment_id"):
        digits = re.sub(r"\D", "", v)
        if len(digits) >= 12:
            return 1.0
        if len(digits) >= 5:
            return 0.55
        return 0.0

    if field == "unit_code":
        return 1.0 if v.upper() in UNIT_CODES else 0.0

    if field == "quantity":
        n = _to_float(v)
        if 0 < n <= 10_000 and n == int(n):
            return 1.0
        if 0 < n <= 10_000:
            return 0.5
        return 0.0

    if field == "tax_rate":
        n = _to_float(v)
        if n in VALID_TAX_RATES:
            return 1.0
        if 0 < n <= 30:
            return 0.25
        return 0.0

    if field == "tax_type":
        return 1.0 if v.upper() in TAX_TYPES else 0.0

    if field in ("rate", "taxable_value", "tax_amount", "total_amount"):
        n = _to_float(v)
        return 1.0 if abs(n) >= 0.01 else 0.0

    return 0.0


def score_row_alignment(row: list[str], mapping: dict[str, int]) -> float:
    if not mapping:
        return 0.0
    total = 0.0
    count = 0
    for field, idx in mapping.items():
        if idx >= len(row):
            continue
        score = score_cell_for_field(field, row[idx])
        weight = 2.0 if field in {"vendor_invoice_no", "tax_rate", "tax_type", "total_amount"} else 1.0
        total += score * weight
        count += weight
    return total / count if count else 0.0


def _pad_row(row: list[str], expected: int) -> list[str]:
    out = list(row)
    while len(out) < expected:
        out.append("")
    return out


def _trim_empty_columns(row: list[str], mapping: dict[str, int], expected: int) -> list[str]:
    """Remove spurious empty columns until row length matches *expected*."""
    current = list(row)
    while len(current) > expected:
        empty_indices = [i for i, c in enumerate(current) if not (c or "").strip()]
        if not empty_indices:
            break
        best_row = current
        best_score = score_row_alignment(current, mapping)
        improved = False
        limit = min(len(empty_indices), 8)
        for remove_idx in empty_indices[:limit]:
            trial = current[:remove_idx] + current[remove_idx + 1 :]
            if len(trial) < expected:
                trial = _pad_row(trial, expected)
            elif len(trial) > expected:
                continue
            score = score_row_alignment(trial, mapping)
            if score > best_score:
                best_score = score
                best_row = trial
                improved = True
        if not improved:
            # Drop trailing extras if still too long
            if len(current) > expected:
                current = current[:expected]
            break
        current = best_row
    return _pad_row(current, expected)


def _reassign_by_content(row: list[str], mapping: dict[str, int], expected: int) -> list[str]:
    """Place each non-empty cell in the column that best matches its content."""
    cells = [(i, (c or "").strip()) for i, c in enumerate(row) if (c or "").strip()]
    if not cells:
        return [""] * expected

    assigned = [""] * expected
    used: set[int] = set()

    for field in FIELD_ASSIGN_ORDER:
        idx = mapping.get(field)
        if idx is None or idx >= expected:
            continue
        best_score = 0.45
        best_cell_idx: int | None = None
        for cell_idx, val in cells:
            if cell_idx in used:
                continue
            s = score_cell_for_field(field, val)
            if s > best_score:
                best_score = s
                best_cell_idx = cell_idx
        if best_cell_idx is not None:
            assigned[idx] = next(v for i, v in cells if i == best_cell_idx)
            used.add(best_cell_idx)

    # Remaining text fragments -> description column
    desc_idx = mapping.get("description")
    if desc_idx is not None and desc_idx < expected:
        leftover = [_clean_cell(v) for i, v in cells if i not in used]
        if leftover:
            existing = assigned[desc_idx]
            merged = " ".join(x for x in ([existing] if existing else []) + leftover if x)
            assigned[desc_idx] = merged.strip()

    return assigned


def _row_has_serial_number(row: list[str], mapping: dict[str, int]) -> bool:
    sl_idx = mapping.get("sl_no")
    if sl_idx is None or sl_idx >= len(row):
        return False
    return bool(re.fullmatch(r"\d+", _clean_code(row[sl_idx])))


def normalize_table_row(
    row: list[str],
    mapping: dict[str, int],
    *,
    continuation: bool = False,
) -> list[str]:
    """Normalize a raw pdfplumber row to exactly the header column count."""
    expected = expected_column_count(mapping)
    if expected <= 0 or not row:
        return list(row)

    current = [(c or "") for c in row]

    # Step 1: trim or pad to exact column count
    if len(current) > expected:
        current = _trim_empty_columns(current, mapping, expected)
    elif len(current) < expected:
        current = _pad_row(current, expected)

    if len(current) > expected:
        current = current[:expected]
    elif len(current) < expected:
        current = _pad_row(current, expected)

    base_score = score_row_alignment(current, mapping)

    # Continuation/tail rows: only fix column COUNT — reassignment would break merge logic.
    if continuation:
        return current

    # Rows with a serial number already in the Sl. No. column: keep pdfplumber layout.
    if _row_has_serial_number(current, mapping):
        return current

    # Full rows with weak alignment: reassign cells by content type.
    if base_score < 0.55:
        reassigned = _reassign_by_content(current, mapping, expected)
        if score_row_alignment(reassigned, mapping) > base_score:
            current = reassigned

    return current
