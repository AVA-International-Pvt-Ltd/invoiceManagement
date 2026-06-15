from __future__ import annotations

import logging
import re
from typing import Any

from ..models import DocumentType, LineItem, Party, RawPage
from .column_align import normalize_table_row as _normalize_table_row
from .pagebreak import (
    ASIN_RE as _ASIN_RE,
    apply_page_break_merge as _apply_page_break_merge,
    build_shifted_continuation_item as _build_shifted_continuation_item,
    consolidate_page_break_items as _consolidate_page_break_items,
    is_duplicate_serial_number as _is_duplicate_serial_number,
    is_immediate_reprint_duplicate as _is_immediate_reprint_duplicate,
    is_page_continuation_row as _is_page_continuation_row,
    is_page2_reprint_duplicate as _is_page2_reprint_duplicate,
    is_summary_polluted_line_item as _is_summary_polluted_line_item,
    item_is_incomplete as _item_is_incomplete,
    looks_like_gstin_fragment as _looks_like_gstin_fragment,
    merge_continuation_rows as _merge_continuation_rows,
    row_description as _row_description,
    row_serial_number as _row_serial_number,
    sanitize_continuation_item as _sanitize_continuation_item,
    try_merge_description_only_row as _try_merge_description_only_row,
)
from .pagebreak import _clean_po_code, _strip_summary_suffix

GSTIN_RE = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z]\d[Z][A-Z\d]\b", re.I)
PAN_RE = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
AMOUNT_RE = re.compile(r"-?[\d,]+\.\d{2}")
DATE_RE = re.compile(
    r"\b(\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4}|\d{4}[-/\.]\d{1,2}[-/\.]\d{1,2})\b"
)

COLUMN_RULES: list[tuple[str, Any]] = [
    ("sl_no", lambda h, c: c in {"slno", "sno", "srno", "si.no", "sino"} or h.startswith(("sl.", "si."))),
    ("description", lambda h, c: any(x in h for x in ("description", "particulars", "item name", "goods", "descriptio"))),
    ("hsn", lambda h, c: "hsn" in h or h == "sac" or "hsn/sac" in h),
    ("asin", lambda h, c: "asin" in h or "asincode" in c),
    ("ean", lambda h, c: "upc" in h or "ean" in c or "upc/ean" in c),
    ("sku", lambda h, c: "sku" in h or "itemcode" in c or "productcode" in c),
    # ETRADE labels the column "PO NO" (compact "pono"); Clicktech labels it
    # "Purchase Order No" (compact "purchaseorderno"). Match either.
    ("purchase_order_no", lambda h, c: "purchaseorder" in c or c == "pono" or ("purchase" in h and "order" in h)),
    ("vendor_invoice_no", lambda h, c: "vendorinvoiceno" in c),
    ("vendor_invoice_date", lambda h, c: "vendorinvoicedate" in c),
    # ETRADE has a per-line-item Return ID column; we don't store it on
    # LineItem (no model field) but reserve the slot so it doesn't accidentally
    # match a different field.
    ("return_id", lambda h, c: c == "returnid" or ("return" in h and "id" in h)),
    ("shipment_id", lambda h, c: c == "shipmentid" or ("shipment" in h and "id" in h)),
    ("unit_code", lambda h, c: "unit/code" in c or "unitcode" in c or ("unit" in h and ("code" in h or "cod" in h))),
    (
        "quantity",
        lambda h, c: h in {"qty", "quantity", "units", "qnty"}
        or c == "qty"
        or "quantity" in h
        or (c.endswith("ntity") and "qua" in c),
    ),
    ("rate", lambda h, c: h == "rate" or "unit price" in h or "cost per unit" in h or "priceperunit" in c),
    ("taxable_value", lambda h, c: "assessable" in c or "taxablevalue" in c or "netamount" in c or "taxable" in h),
    ("tax_rate", lambda h, c: ("gstrate" in c or "taxrate" in c) and "%" in h + c),
    ("tax_type", lambda h, c: "taxtype" in c),
    ("tax_amount", lambda h, c: ("gstvalue" in c or "taxamount" in c) and "rate" not in c),
    ("total_amount", lambda h, c: "totalamount" in c or (c.startswith("total") and "amount" in c)),
]


def parse_document(file_name: str, pages: list[RawPage]) -> dict[str, Any]:
    full_text = "\n".join(page.raw_text for page in pages)
    doc_type = _classify(file_name, full_text)
    addresses = _extract_addresses(full_text, pages=pages)
    header = _extract_header(full_text, doc_type)
    _finalize_etrade_header(header, file_name, full_text)
    parties = _extract_parties(full_text, addresses)
    if not parties["vendor"].pan and header.get("vendor_pan"):
        parties["vendor"] = parties["vendor"].model_copy(update={"pan": header["vendor_pan"]})
    if header.get("receiver_pan"):
        for key in ("receiver_billing", "receiver_shipping"):
            if addresses.get(key) and not addresses[key].get("pan"):
                addresses[key]["pan"] = header["receiver_pan"]
    tax_summary = _extract_tax_summary(full_text)
    totals = _extract_totals(full_text)
    line_items = _extract_line_items(pages, header, doc_type, parties["vendor"])
    _reconcile_tax_totals(totals, tax_summary, line_items)

    return {
        "document_type": doc_type,
        "classification_confidence": 0.82 if doc_type != DocumentType.unknown else 0.45,
        "header": header,
        "vendor": parties["vendor"],
        "customer": parties["customer"],
        "billing_address": addresses["billing"],
        "shipping_address": addresses["shipping"],
        "receiver_billing_address": addresses["receiver_billing"],
        "receiver_shipping_address": addresses["receiver_shipping"],
        "tax_summary": tax_summary,
        "totals": totals,
        "line_items": line_items,
    }


def _classify(file_name: str, text: str) -> DocumentType:
    haystack = f"{file_name}\n{text}".lower()
    # IMPORTANT: more-specific phrases must come BEFORE the broader rules.
    # "Cancellation of Request for Credit" contains "request for credit"
    # but is structurally a credit-note variant (uses Credit Note No fields).
    rules = [
        (("cancellation of request for credit",), DocumentType.credit_note),
        (("gst credit note", "credit note", "credit memo"), DocumentType.credit_note),
        (("request for credit", "r4c", "return claim"), DocumentType.r4c),
        (("debit note no", "debit note"), DocumentType.debit_note),
        (("settlement report", "settlement"), DocumentType.settlement),
        # Invoice rules MUST run before the purchase-order rule because the
        # ETRADE invoice line-item table contains a "PO" column header that
        # leaks into the extracted text as a stand-alone " po " token —
        # which would otherwise trigger the broad PO rule below.
        (("gst invoice", "tax invoice", "bill of supply"), DocumentType.invoice),
        (("purchase order", " po ", "p.o."), DocumentType.purchase_order),
    ]
    for keywords, doc_type in rules:
        if any(keyword in haystack for keyword in keywords):
            return doc_type
    return DocumentType.unknown


# Canonical PDF titles (longest / most-specific patterns first).
_DOCUMENT_HEADING_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("Cancellation of Request for Credit", re.compile(r"Cancellation\s+(?:of\s+)?Request\s+for\s+Credit", re.I)),
    ("GST Credit Note", re.compile(r"GST\s+Credit\s+Note", re.I)),
    ("Request for Credit", re.compile(r"Request\s+for\s+Credit", re.I)),
    ("GST Invoice", re.compile(r"GST\s+Invoice", re.I)),
    ("Tax Invoice", re.compile(r"Tax\s+Invoice", re.I)),
    ("Debit Note", re.compile(r"Debit\s+Note", re.I)),
    ("Bill of Supply", re.compile(r"Bill\s+of\s+Supply", re.I)),
]


def _extract_document_heading(text: str) -> str:
    """Read the document title printed at the top of the PDF (e.g. Request for Credit)."""
    sample = text[:3000]
    for canonical, pattern in _DOCUMENT_HEADING_RULES:
        if pattern.search(sample):
            return canonical

    for line in text.splitlines()[:20]:
        cleaned = _clean_cell(line)
        if not cleaned:
            continue
        if re.match(r"^Page \d+ of \d+$", cleaned, re.I):
            continue
        lowered = cleaned.lower()
        if lowered.startswith(("billing address", "shipping address", "receiver")):
            break
        if len(cleaned) > 80 or GSTIN_RE.search(cleaned) or PAN_RE.search(cleaned):
            continue
        return cleaned

    return ""


def _first_match(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.S)
        if match:
            return _clean_cell(match.group(1))
    return ""


# All known field labels that appear across all Clicktech document headers
# (R4C / Debit Note / GST Invoice / Credit Note).
# Used to bound a field's captured value so an empty field doesn't swallow
# the next field's label as its value, and to reject matches that are
# embedded inside a longer label (e.g. "Invoice No" inside
# "Original Debit Note/Invoice No").
_HEADER_LABELS = (
    "Original Debit Note/Invoice No",
    "Original Debit Note/Invoice Date",
    "Original Invoice No",
    "Original Invoice Date",
    "System Ref No",
    "Debit Note No",
    "Debit Note Date",
    "Credit Note No",
    "Credit Note Date",
    "Invoice No",
    "Invoice Number",
    "Invoice Date",
    "RMA No",
    "Due Date",
    "Return ID",
    "Payment Method",
    "Removal ID",
    "Reason for Issuing Debit Note",
    "Reason for Issuing Credit Note",
    "Reason for Issuing Debit",
    "Reason for Issuing Credit",
    "Reason",
    "VRET Shipment ID",
    "Shipment ID",
    "Payment Term",
    "Call Tag ID",
    "Place of Supply",
    "InvoiceReferenceNumber",
    "Invoice Reference Number",
    "IRN",
    "Currency",
)


def _label_pattern(label: str) -> str:
    """Convert a label literal into a regex fragment that:
    - tolerates the label wrapping across newlines (any whitespace between words)
    - escapes regex special characters
    - escapes the embedded forward slashes / spaces literally
    """
    parts = [re.escape(part) for part in label.split(" ")]
    return r"\s+".join(parts)


def _extract_field(text: str, label: str, multiline: bool = False) -> str:
    """Capture the value that follows ``label :`` and ends at the start of
    any other known label (or end of line / end of section).

    Empty fields like ``Return ID :`` correctly resolve to ``""`` because the
    immediate next non-whitespace token is another known label and the value
    capture group is allowed to be empty.

    A lookbehind prevents a short label like ``Invoice No`` from matching
    inside a longer label like ``Original Debit Note/Invoice No``.

    When ``multiline=True`` the value can span multiple lines; it then ends
    only at the next known label (used for free-text fields like ``Reason``).
    """
    other_labels = [l for l in _HEADER_LABELS if l != label]
    other_labels.sort(key=len, reverse=True)  # match longer labels first
    boundary = "|".join(_label_pattern(lbl) for lbl in other_labels)

    label_re = _label_pattern(label)
    # Reject when preceded by alphanumeric or slash (i.e. inside a longer label),
    # and also reject when the label is immediately preceded by "Original " so
    # short labels like "Invoice No" / "Invoice Date" don't match inside
    # "Original Invoice No" / "Original Invoice Date" (ETRADE Cancellation).
    lookbehind = r"(?<![A-Za-z0-9/])(?<!Original\s)"

    if multiline:
        # In multiline mode the value can span lines. Stop at the next known
        # label, or at an isolated "Note" line (which is the trailing wrap of
        # the "Reason for Issuing Debit Note" / "...Credit Note" label that the
        # PDF prints AFTER the value), or end-of-text.
        terminator = rf"(?=\s+(?:{boundary})\s*:|\nNote\s*(?:\n|$)|$)"
        flags = re.I | re.S
    else:
        terminator = rf"(?=\s+(?:{boundary})\s*:|\n|$)"
        flags = re.I

    pattern = (
        rf"{lookbehind}{label_re}\s*:[ \t]*"
        rf"(?P<value>.*?)"
        rf"{terminator}"
    )
    match = re.search(pattern, text, flags)
    if not match:
        return ""
    value = match.group("value").strip()
    # If the captured value IS another field's label (i.e. the field on this
    # PDF was empty and the regex slipped past the colon), reject it.
    for lbl in other_labels:
        if re.match(rf"^{_label_pattern(lbl)}\s*:", value, re.I):
            return ""
    # Collapse internal whitespace runs (esp. newlines from wrapped values)
    # into single spaces.
    return re.sub(r"\s+", " ", _clean_cell(value))


def _extract_header(text: str, doc_type: DocumentType) -> dict[str, str]:
    header = {
        "invoice_number": "",
        "invoice_date": "",
        "document_number": "",
        "document_date": "",
        "credit_note_number": "",
        "credit_note_date": "",
        "debit_note_number": "",
        "debit_note_date": "",
        "original_invoice_number": "",
        "original_invoice_date": "",
        "rma_number": "",
        "return_id": "",
        "removal_id": "",
        "shipment_id": "",
        "vret_shipment_id": "",
        "due_date": "",
        "payment_method": "",
        "payment_terms": "",
        "reason": "",
        "call_tag_id": "",
        "place_of_supply": "",
        "invoice_reference_number": "",
        "po_number": "",
        "currency": "INR",
        "irn": "",
        "system_ref_no": "",
        "document_heading": "",
        "vendor_pan": "",
        "receiver_pan": "",
    }

    header["debit_note_number"] = _extract_field(text, "Debit Note No")
    header["debit_note_date"] = _extract_field(text, "Debit Note Date")
    header["credit_note_number"] = _extract_field(text, "Credit Note No")
    header["credit_note_date"] = _extract_field(text, "Credit Note Date")
    header["rma_number"] = _extract_field(text, "RMA No")
    header["return_id"] = _extract_field(text, "Return ID")
    header["removal_id"] = _extract_field(text, "Removal ID")
    vret = _extract_field(text, "VRET Shipment ID")
    if not vret:
        vret = _extract_field(text, "Shipment ID")
    header["vret_shipment_id"] = vret
    header["due_date"] = _extract_field(text, "Due Date")
    header["payment_method"] = _extract_field(text, "Payment Method")
    header["payment_terms"] = _extract_field(text, "Payment Term")
    # Reason can wrap as "Reason for Issuing Debit\nNote" (label wraps) OR
    # the *value* can wrap to a second line (Credit Note format).
    # Try longer label forms first, with multiline value capture so the value
    # can span lines until the next known label is reached.
    header["reason"] = (
        _extract_field(text, "Reason for Issuing Debit Note", multiline=True)
        or _extract_field(text, "Reason for Issuing Credit Note", multiline=True)
        or _extract_field(text, "Reason for Issuing Debit", multiline=True)
        or _extract_field(text, "Reason for Issuing Credit", multiline=True)
        or _extract_field(text, "Reason", multiline=True)
    )
    if not header["reason"]:
        reason_match = re.search(
            r"Reason for Issuing[^:]*:\s*(.+?)(?=\n[A-Z]|\Z)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if reason_match:
            header["reason"] = _clean_cell(reason_match.group(1))
    header["call_tag_id"] = _extract_field(text, "Call Tag ID")
    header["place_of_supply"] = _extract_field(text, "Place of Supply")
    header["invoice_reference_number"] = _extract_field(text, "InvoiceReferenceNumber") or _extract_field(text, "Invoice Reference Number")
    # Reference to the original document this credit note cancels.
    header["original_invoice_number"] = (
        _extract_field(text, "Original Debit Note/Invoice No")
        or _extract_field(text, "Original Invoice No")
    )
    header["original_invoice_date"] = (
        _extract_field(text, "Original Debit Note/Invoice Date")
        or _extract_field(text, "Original Invoice Date")
    )
    # GST Invoice format uses standalone "Invoice No :" / "Invoice Date :" headers,
    # while R4C / Debit Note formats omit them. The label-aware extractor now has
    # a lookbehind that prevents matching inside "Original Debit Note/Invoice No",
    # so a Credit Note correctly resolves invoice_number to "".
    # Try the longer "Invoice Number" label first so it wins over the shorter
    # "Invoice No" when both could match different fields on the same page.
    header["invoice_number"] = _extract_field(text, "Invoice Number") or _extract_field(text, "Invoice No")
    header["invoice_date"] = _extract_field(text, "Invoice Date")
    # ETRADE "Cancellation of Request for Credit" prints the credit-note
    # identifier under "Invoice Number :" (e.g. HRCN2025-27534) rather than
    # "Credit Note No :". Promote that value and keep invoice_number empty.
    if (
        not header["credit_note_number"]
        and "cancellation of request for credit" in text.lower()
        and header["invoice_number"]
    ):
        header["credit_note_number"] = header["invoice_number"]
        header["invoice_number"] = ""
    # ETRADE "Request for Credit" prints the debit-note identifier under
    # "Invoice Number :" (e.g. KADN2025-11793) rather than "Debit Note No :".
    elif (
        not header["debit_note_number"]
        and "request for credit" in text.lower()
        and "cancellation of request for credit" not in text.lower()
        and header["invoice_number"]
    ):
        header["debit_note_number"] = header["invoice_number"]
        header["invoice_number"] = ""
    # ETRADE prints a per-document "System Ref No" alongside the invoice
    # number. It maps to the file name (e.g. 30000877790.pdf) and is the
    # most stable per-document identifier.
    header["system_ref_no"] = _extract_field(text, "System Ref No")
    header["irn"] = _first_match(text, [r"\b([0-9a-f]{64})\b"])

    vendor_pan_match = re.search(r"PAN:\s*([A-Z]{5}\d{4}[A-Z])", text)
    header["vendor_pan"] = vendor_pan_match.group(1) if vendor_pan_match else ""

    receiver_pan_match = re.search(r"PAN No:\s*([A-Z]{5}\d{4}[A-Z])", text)
    header["receiver_pan"] = receiver_pan_match.group(1) if receiver_pan_match else ""

    # document_date: prefer the most specific date for the doc type.
    if header["debit_note_date"]:
        header["document_date"] = header["debit_note_date"]
    elif header["credit_note_date"]:
        header["document_date"] = header["credit_note_date"]
    elif header["invoice_date"]:
        header["document_date"] = header["invoice_date"]

    if header["debit_note_number"]:
        header["document_number"] = header["debit_note_number"]
    elif header["credit_note_number"]:
        header["document_number"] = header["credit_note_number"]
    elif header["invoice_number"]:
        header["document_number"] = header["invoice_number"]

    header["document_heading"] = _extract_document_heading(text)

    return header


def _is_etrade_document(text: str) -> bool:
    haystack = text.lower()
    return "etrade" in haystack or "aadcv4254h" in haystack


def _filename_system_ref(file_name: str) -> str:
    """ETRADE PDFs are named after the System Ref No (e.g. 30000877790.pdf)."""
    stem = re.sub(r"\s+", "", (file_name or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1])
    stem = re.sub(r"\.[^.]+$", "", stem, flags=re.I)
    if re.fullmatch(r"\d{8,14}", stem):
        return stem
    return ""


def _clean_reference_number(value: str) -> str:
    cleaned = _clean_cell(value)
    if not cleaned:
        return ""
    if "irn not generated" in cleaned.lower():
        return ""
    return cleaned


def _finalize_etrade_header(header: dict[str, str], file_name: str, text: str) -> None:
    """Fill ETRADE-specific header fields and normalize reference values."""
    if not _is_etrade_document(text):
        return

    if not header.get("system_ref_no"):
        header["system_ref_no"] = _filename_system_ref(file_name)

    lowered = text.lower()
    # ETRADE GST Credit Note prints the credit-note id under "Invoice Number :".
    if (
        not header.get("credit_note_number")
        and "gst credit note" in lowered
        and "cancellation of request for credit" not in lowered
        and header.get("invoice_number")
    ):
        header["credit_note_number"] = header["invoice_number"]
        header["invoice_number"] = ""
        if not header.get("credit_note_date") and header.get("invoice_date"):
            header["credit_note_date"] = header["invoice_date"]
            header["invoice_date"] = ""

    header["invoice_reference_number"] = _clean_reference_number(
        header.get("invoice_reference_number") or ""
    )

    if header.get("debit_note_number"):
        header["document_number"] = header["debit_note_number"]
    elif header.get("credit_note_number"):
        header["document_number"] = header["credit_note_number"]
    elif header.get("invoice_number"):
        header["document_number"] = header["invoice_number"]


def _empty_address() -> dict[str, str]:
    return {
        "name": "",
        "address": "",
        "city": "",
        "state": "",
        "postal_code": "",
        "country": "",
        "gstin": "",
        "state_code": "",
        "pan": "",
        "place_of_supply": "",
    }


def _extract_addresses(text: str, pages: list[RawPage] | None = None) -> dict[str, dict[str, str]]:
    """Extract the 4 address blocks (billing / receiver_billing / shipping /
    receiver_shipping) from a Clicktech R4C document.

    When word-level bboxes are available (``pages[0].coordinates``), use a
    column split based on the x-coordinate of the "Address:" label words.
    Otherwise fall back to the older text-only heuristic.
    """
    result = {
        "billing": _empty_address(),
        "receiver_billing": _empty_address(),
        "shipping": _empty_address(),
        "receiver_shipping": _empty_address(),
    }

    if pages and pages[0].coordinates:
        bbox_result = _extract_addresses_bbox(pages[0].coordinates)
        if bbox_result:
            return bbox_result

    billing_block = _slice_block(
        text,
        r"Billing Address:\s*Receiver Billing Address:",
        r"Shipping Address:\s*Receiver Shipping Address:",
    )
    shipping_block = _slice_block(
        text,
        r"Shipping Address:\s*Receiver Shipping Address:",
        r"InvoiceReferenceNumber|Debit Note No",
    )

    if billing_block:
        left, right = _split_dual_column_block(billing_block)
        result["billing"] = _build_address(left)
        result["receiver_billing"] = _build_address(right)

    if shipping_block:
        left, right = _split_dual_column_block(shipping_block)
        result["shipping"] = _build_address(left)
        receiver_shipping = _build_address(right)
        place = _first_match(shipping_block, [r"Place of Supply\s*:\s*(.+)"])
        if place:
            receiver_shipping["place_of_supply"] = place
        result["receiver_shipping"] = receiver_shipping
        if not result["shipping"]["name"] or not _looks_like_company_name(result["shipping"]["name"]):
            result["shipping"]["name"] = result["billing"]["name"]

    return result


def _extract_addresses_bbox(words: list[dict]) -> dict[str, dict[str, str]] | None:
    """Bbox-aware address extraction.

    Strategy:
        1. Locate the y-positions of "Billing Address:", "Shipping Address:",
           "InvoiceReferenceNumber" / "Debit Note No" markers.
        2. The x-position of "Receiver Billing Address:" defines the column
           split (everything left of it is the left column).
        3. Group words within each y-range into rows by ``top`` and into
           columns by their x0 vs the split.
        4. Build the 4 address dicts row-by-row using the same _build_address
           helper.
    """
    if not words:
        return None

    def find(text_to_find: str) -> dict | None:
        for w in words:
            if w["text"].lower() == text_to_find.lower():
                return w
        return None

    # Find anchors. Locate the column split via "Receiver" word(s).
    billing_anchor = find("Billing")
    shipping_anchor = find("Shipping")
    invoice_ref_anchor = None
    for w in words:
        if w["text"].startswith("InvoiceReferenceNumber"):
            invoice_ref_anchor = w
            break

    # ETRADE prints the IRN as four separate words ("Invoice Reference
    # Number :"), not as a single token. Fall back to the first "Invoice"
    # word that appears below the shipping anchor — that's where the
    # address section ends and the document metadata begins.
    if not invoice_ref_anchor and shipping_anchor:
        candidates = [
            w
            for w in words
            if w["text"] == "Invoice" and w["top"] > shipping_anchor["bottom"]
        ]
        if candidates:
            invoice_ref_anchor = min(candidates, key=lambda w: w["top"])

    # Clicktech ends the address block at "Debit Note No :". Require "Note"
    # and "No" on the same row so we don't stop at "Debit Note Date" or
    # "Reason for Issuing Debit" (both appear later on ETRADE R4C pages).
    if not invoice_ref_anchor and shipping_anchor:
        for w in words:
            if w["text"] != "Debit" or w["top"] <= shipping_anchor["bottom"]:
                continue
            row_mates = [x for x in words if abs(x["top"] - w["top"]) < 4]
            row_texts = {x["text"] for x in row_mates}
            if "Note" in row_texts and "No" in row_texts:
                invoice_ref_anchor = w
                break

    receiver_words = [w for w in words if w["text"].lower() == "receiver"]
    if not receiver_words:
        return None
    column_split = min(rw["x0"] for rw in receiver_words) - 5  # a bit of margin

    # The y-range for the *billing block* is from just below the first
    # "Billing Address:" header to just above the "Shipping Address:" header.
    if not billing_anchor or not shipping_anchor:
        return None
    billing_y0 = billing_anchor["bottom"]
    billing_y1 = shipping_anchor["top"]

    shipping_y0 = shipping_anchor["bottom"]
    shipping_y1 = invoice_ref_anchor["top"] if invoice_ref_anchor else 1e9

    def words_in(y0: float, y1: float) -> list[dict]:
        return [w for w in words if y0 < w["top"] < y1]

    def split_columns(block_words: list[dict]) -> tuple[list[str], list[str], dict | None]:
        """Group words into rows by their y-position, then split each row at
        ``column_split``. Returns (left_lines, right_lines, place_of_supply)."""
        if not block_words:
            return [], [], None
        block_words = sorted(block_words, key=lambda w: (w["top"], w["x0"]))
        rows: list[list[dict]] = []
        current: list[dict] = []
        current_top = None
        for w in block_words:
            if current_top is None or abs(w["top"] - current_top) < 4:
                current.append(w)
                current_top = w["top"] if current_top is None else current_top
            else:
                rows.append(current)
                current = [w]
                current_top = w["top"]
        if current:
            rows.append(current)

        left_lines: list[str] = []
        right_lines: list[str] = []
        place_of_supply: str | None = None

        for row in rows:
            row.sort(key=lambda w: w["x0"])
            left_words = [w["text"] for w in row if w["x0"] < column_split]
            right_words = [w["text"] for w in row if w["x0"] >= column_split]

            left_text = " ".join(left_words).strip()
            right_text = " ".join(right_words).strip()

            # Skip the "Billing Address:" / "Shipping Address:" / "Receiver"
            # banner rows themselves.
            if left_text.lower().startswith(("billing address", "shipping address")):
                left_text = ""
            if right_text.lower().startswith(("receiver billing address", "receiver shipping address")):
                right_text = ""

            # Pull out a Place of Supply line for the receiver shipping block.
            pos = re.search(r"Place of Supply\s*:\s*(.+)", left_text + " " + right_text, re.I)
            if pos:
                place_of_supply = pos.group(1).strip()
                # Strip the place-of-supply portion out so it doesn't leak into
                # the address body.
                left_text = re.sub(r"Place of Supply\s*:\s*.+", "", left_text, flags=re.I).strip()
                right_text = re.sub(r"Place of Supply\s*:\s*.+", "", right_text, flags=re.I).strip()

            if left_text:
                left_lines.append(left_text)
            if right_text:
                right_lines.append(right_text)

        left_lines = [ln for ln in left_lines if not _is_address_noise_line(ln)]
        right_lines = [ln for ln in right_lines if not _is_address_noise_line(ln)]

        return left_lines, right_lines, place_of_supply

    bill_left, bill_right, _ = split_columns(words_in(billing_y0, billing_y1))
    ship_left, ship_right, place = split_columns(words_in(shipping_y0, shipping_y1))

    billing = _build_address(bill_left)
    receiver_billing = _build_address(bill_right)
    shipping = _build_address(ship_left)
    receiver_shipping = _build_address(ship_right)

    # If the shipping section omitted the company name, inherit from billing.
    if not shipping["name"] or not _looks_like_company_name(shipping["name"]):
        shipping["name"] = billing["name"]
    if not receiver_shipping["name"]:
        receiver_shipping["name"] = receiver_billing["name"]

    if place:
        receiver_shipping["place_of_supply"] = place

    return {
        "billing": billing,
        "receiver_billing": receiver_billing,
        "shipping": shipping,
        "receiver_shipping": receiver_shipping,
    }


def _slice_block(text: str, start_pattern: str, end_pattern: str) -> str:
    match = re.search(rf"{start_pattern}\s*\n(.*?)(?={end_pattern})", text, re.I | re.S)
    return match.group(1).strip() if match else ""


def _split_line_at_markers(line: str, markers: list[str]) -> tuple[str, str]:
    earliest = len(line)
    marker_hit = ""
    for marker in markers:
        idx = line.find(marker)
        if idx != -1 and idx < earliest:
            earliest = idx
            marker_hit = marker
    if not marker_hit:
        return line, ""
    return line[:earliest].strip().rstrip(","), line[earliest:].strip()


def _split_dual_column_block(block: str) -> tuple[list[str], list[str]]:
    left_lines: list[str] = []
    right_lines: list[str] = []
    right_markers = ["AVA INTERNATIONAL", "KHASRA NO.", "ALIPUR", "DELHI-"]

    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("Place of Supply:"):
            right_lines.append(line)
            continue

        if "GSTIN:" in line or "GSTID:" in line:
            gstin = _first_match(line, [r"GSTIN:\s*(\S+)"])
            gstid = _first_match(line, [r"GSTID:\s*(\S+)"])
            if gstin:
                left_lines.append(f"GSTIN: {gstin}")
            if gstid:
                right_lines.append(f"GSTID: {gstid}")
            continue

        if "State Code" in line:
            codes = re.findall(r"State Code:\s*([A-Z]{2})", line, re.I)
            if codes:
                left_lines.append(f"State Code: {codes[0]}")
                if len(codes) > 1:
                    right_lines.append(f"State Code: {codes[1]}")
            pan = _first_match(line, [r"PAN\s*(?:No)?\s*:?\s*([A-Z]{5}\d{4}[A-Z])"])
            if pan:
                right_lines.append(f"PAN: {pan}")
            continue

        left_part, right_part = _split_line_at_markers(line, right_markers)
        if left_part:
            left_lines.append(left_part)
        if right_part:
            right_lines.append(right_part)

    return left_lines, right_lines


_PIN_RE = re.compile(r"\b(\d{6})\b")
_STRICT_PAN_RE = re.compile(r"^[A-Z]{5}\d{4}[A-Z]$")

# Map 2-letter Indian state codes to their full state name. Used as a fallback
# in address blocks where only "State Code: MH" is printed (ETRADE format)
# without a separate state-name line.
_STATE_CODE_TO_NAME = {
    "AN": "Andaman and Nicobar Islands", "AP": "Andhra Pradesh",
    "AR": "Arunachal Pradesh", "AS": "Assam", "BR": "Bihar",
    "CH": "Chandigarh", "CG": "Chhattisgarh", "DD": "Daman and Diu",
    "DL": "Delhi", "DN": "Dadra and Nagar Haveli", "GA": "Goa",
    "GJ": "Gujarat", "HP": "Himachal Pradesh", "HR": "Haryana",
    "JH": "Jharkhand", "JK": "Jammu and Kashmir", "KA": "Karnataka",
    "KL": "Kerala", "LA": "Ladakh", "LD": "Lakshadweep",
    "MH": "Maharashtra", "ML": "Meghalaya", "MN": "Manipur",
    "MP": "Madhya Pradesh", "MZ": "Mizoram", "NL": "Nagaland",
    "OD": "Odisha", "OR": "Odisha", "PB": "Punjab", "PY": "Puducherry",
    "RJ": "Rajasthan", "SK": "Sikkim", "TG": "Telangana",
    "TN": "Tamil Nadu", "TR": "Tripura", "TS": "Telangana",
    "UK": "Uttarakhand", "UP": "Uttar Pradesh", "WB": "West Bengal",
}

_STATE_NAMES = {
    "ANDHRA PRADESH", "ARUNACHAL PRADESH", "ASSAM", "BIHAR", "CHHATTISGARH",
    "GOA", "GUJARAT", "HARYANA", "HIMACHAL PRADESH", "JHARKHAND", "KARNATAKA",
    "KERALA", "MADHYA PRADESH", "MAHARASHTRA", "MANIPUR", "MEGHALAYA",
    "MIZORAM", "NAGALAND", "ODISHA", "PUNJAB", "RAJASTHAN", "SIKKIM",
    "TAMIL NADU", "TELANGANA", "TRIPURA", "UTTAR PRADESH", "UTTARAKHAND",
    "WEST BENGAL", "DELHI", "JAMMU AND KASHMIR", "LADAKH", "PUDUCHERRY",
    "CHANDIGARH", "DADRA AND NAGAR HAVELI",
    # 2-letter state-codes that may sit alone on a line
    "HR", "DL", "MH", "KA", "TN", "UP", "WB", "GJ", "RJ", "PB", "BR",
    "OD", "TG", "AP", "MP", "CG", "JH", "AS", "KL", "HP", "UK",
}


def _is_pan_token(value: str) -> bool:
    return bool(_STRICT_PAN_RE.match(value.strip()))


def _looks_like_street_or_building(line: str) -> bool:
    """True when a line is a warehouse/street row, not a company name."""
    stripped = line.strip()
    if not stripped:
        return False
    if re.match(
        r"^(?:Building|Pin\b|Plot|Khasra|KHASRA|Shop|Flat|Unit|Village|Rect|Floor|Door|"
        r"Gate|Warehouse|Tal:|Dist:|\d+/|\d+\s)",
        stripped,
        re.I,
    ):
        return True
    if re.search(r"\b(?:Tal:|Dist:|Pin\s+\d{6})\b", stripped, re.I):
        return True
    return False


def _looks_like_company_name(line: str) -> bool:
    """A first body line is a company name when it contains a corporate suffix
    (Pvt, Ltd, Limited, Private, etc.) or is entirely uppercase words. A street
    line ("Rect/Killa Nos. ...") fails both tests."""
    if _looks_like_street_or_building(line):
        return False
    if re.search(r"\b(Limited|Ltd|Private|Pvt|Inc|Corp|Industries|Enterprises|Retail|International)\b", line, re.I):
        return True
    words = line.split()
    if len(words) >= 2 and all(re.match(r"^[A-Z][A-Z0-9.,()&/\-]*$", w) for w in words):
        return True
    return False


def _normalize_name_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _is_duplicate_name_line(line: str, name: str) -> bool:
    line_key = _normalize_name_key(line)
    name_key = _normalize_name_key(name)
    if not line_key or not name_key:
        return False
    if line_key == name_key:
        return True
    shorter, longer = sorted((line_key, name_key), key=len)
    return shorter in longer and len(shorter) >= int(len(longer) * 0.85)


def _is_address_noise_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if re.match(r"^:\s*[0-9a-f]{20,}$", stripped, re.I):
        return True
    if re.fullmatch(r"[0-9a-f]{40,}", stripped, re.I):
        return True
    return False


# Suffix tokens that signal the end of a company name when followed by a comma
# (e.g. "Clicktech Retail Private Limited, Rectangle number 34/35/...").
_COMPANY_SUFFIX_RE = re.compile(
    r"^(.*?\b(?:Limited|Ltd\.?|Private|Pvt\.?|Inc\.?|Corp\.?|"
    r"Industries|Enterprises|LLP|L\.L\.P\.?)\b)\s*,\s*(.+)$",
    re.I,
)


def _split_name_from_street(line: str) -> tuple[str, str]:
    """If a body line packs the company name and the street address together
    like 'Clicktech Retail Private Limited, Rectangle number 34/35/41/60/66',
    split at the first comma AFTER the corporate-suffix word and return
    ``(name, street_remainder)``. Otherwise returns ``(line, "")`` unchanged.
    """
    m = _COMPANY_SUFFIX_RE.match(line)
    if m:
        return m.group(1).strip().rstrip(","), m.group(2).strip()
    return line, ""


def _merge_split_label_lines(lines: list[str]) -> list[str]:
    """Merge a label-only line with its value on the next line.

    ETRADE PDFs print the receiver's GSTIN as ``GSTIN:`` on one line and the
    value (``07AATCA0039M1ZD``) on the next. The line-by-line address parser
    expects ``label: value`` on a single line, so collapse the pair before
    parsing.
    """
    merged: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Match "GSTIN:" / "GSTID:" with no value after the colon.
        label_match = re.match(r"^(GSTIN|GSTID)\s*:\s*$", line, re.I)
        if label_match and i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            if GSTIN_RE.fullmatch(next_line):
                merged.append(f"{label_match.group(1)}: {next_line}")
                i += 2
                continue
        merged.append(line)
        i += 1
    return merged


def _extract_postal(address_text: str) -> str:
    """Extract a 6-digit postal code from mixed vendor address formats."""
    if not address_text:
        return ""
    m = re.search(r"State Code:\s*\w+\s*-\s*(\d{6})", address_text, re.I)
    if m:
        return m.group(1)
    m = re.search(r"(?:India|[A-Z]+)-(\d{6})", address_text, re.I)
    if m:
        return m.group(1)
    return ""


def _build_address(lines: list[str]) -> dict[str, str]:
    address = _empty_address()
    body_lines: list[str] = []

    lines = _merge_split_label_lines(lines)

    for line in lines:
        if line.startswith(("GSTIN:", "GSTID:")):
            address["gstin"] = line.split(":", 1)[1].strip()
            continue
        if line.startswith("State Code:") or line.startswith("State Code :"):
            value = line.split(":", 1)[1].strip()
            # ETRADE prints the postal code on the State Code line:
            # "State Code: MH - 440018". Capture both parts.
            sc_match = re.match(r"([A-Z]{1,3})\s*(?:[-\u2013\u2014]\s*(\d{6}))?", value)
            if sc_match:
                address["state_code"] = sc_match.group(1)
                if sc_match.group(2) and not address["postal_code"]:
                    address["postal_code"] = sc_match.group(2)
            continue
        if "PAN" in line and ":" in line and "PAN" in line.split(":", 1)[0]:
            value = line.split(":", 1)[1].strip()
            if _is_pan_token(value):
                address["pan"] = value
            continue
        if line.startswith("Place of Supply:"):
            address["place_of_supply"] = line.split(":", 1)[1].strip()
            continue
        if _is_address_noise_line(line):
            continue
        body_lines.append(line)

    if not body_lines:
        return address

    # First line is the company name only if it actually looks like a company.
    # When the first line packs ``Name, Street ...`` together (Format 4 shipping
    # block), split at the first comma after the corporate suffix so the street
    # portion stays with the address rather than being captured as the name.
    if _looks_like_company_name(body_lines[0]):
        name, street_remainder = _split_name_from_street(body_lines[0])
        address["name"] = name
        tail = body_lines[1:]
        if street_remainder:
            tail = [street_remainder] + tail
    else:
        tail = body_lines[:]

    if address["name"]:
        tail = [line for line in tail if not _is_duplicate_name_line(line, address["name"])]
    state_idx: int | None = None
    pin_idx: int | None = None
    country_idx: int | None = None

    for i, part in enumerate(tail):
        part_upper = part.upper().strip()

        # "India-122413" — country + pin on one line.
        m = re.search(r"\bIndia\s*-\s*(\d{6})\b", part, re.I)
        if m:
            address["postal_code"] = m.group(1)
            if not address["country"]:
                address["country"] = "India"
            pin_idx = i
            country_idx = i
            continue

        # "DELHI-110036" — state name + pin on one line.
        m = re.match(r"^([A-Z][A-Z\s]+?)\s*-\s*(\d{6})$", part.strip())
        if m and m.group(1).strip() in _STATE_NAMES:
            address["state"] = m.group(1).strip()
            address["postal_code"] = m.group(2)
            state_idx = i
            pin_idx = i
            continue

        # Bare INDIA (right column country).
        if part_upper == "INDIA":
            if not address["country"]:
                address["country"] = "INDIA"
            country_idx = i
            continue

        # Bare 6-digit pin.
        pin_match = _PIN_RE.search(part)
        if pin_match and not address["postal_code"]:
            address["postal_code"] = pin_match.group(1)
            pin_idx = i if pin_idx is None else pin_idx
            continue

        # Bare state name / 2-letter code.
        if part_upper in _STATE_NAMES and not address["state"]:
            address["state"] = part if len(part) > 2 else part_upper
            state_idx = i
            continue

    # The city is the line immediately before the state line (or, failing
    # that, immediately before the pin/country line).
    boundary_idx = state_idx if state_idx is not None else pin_idx
    if boundary_idx is None:
        boundary_idx = country_idx
    city_idx: int | None = None
    if boundary_idx is not None and boundary_idx > 0:
        city_idx = boundary_idx - 1
        # If the candidate is itself a state line ("State-name pin" combo),
        # walk back further.
        while city_idx > 0 and city_idx in {state_idx, pin_idx, country_idx}:
            city_idx -= 1
        if city_idx >= 0:
            candidate = tail[city_idx].strip().rstrip(",")
            if candidate and candidate.upper() != "INDIA" and not _PIN_RE.search(candidate):
                address["city"] = candidate

    # ETRADE fallback: when state_code / postal_code came from the
    # "State Code: MH - 440018" line and were stripped out *before* the
    # body-line walk, no state/pin marker remains inside ``tail`` to anchor
    # the city. In that case the last body line IS the city ("NAGPUR" /
    # "NEW DELHI").
    if (
        city_idx is None
        and tail
        and (address["postal_code"] or address["state_code"])
        and not address["city"]
    ):
        last_idx = len(tail) - 1
        candidate = tail[last_idx].strip().rstrip(",")
        if candidate and candidate.upper() != "INDIA" and not _PIN_RE.search(candidate):
            address["city"] = candidate
            city_idx = last_idx

    # Street/address is every line before the city, joined.
    if city_idx is not None and city_idx > 0:
        street_parts = tail[:city_idx]
    elif city_idx == 0:
        street_parts = []
    else:
        # No clear city found — use everything as the address.
        street_parts = tail
    address["address"] = ", ".join(street_parts).strip(", ")

    address["address"] = _clean_cell(address["address"])
    address["name"] = _clean_cell(address["name"])

    # ETRADE prints only the 2-letter state code ("State Code: MH - 440018")
    # without a separate state-name line. Fill the full state name from the
    # known mapping so downstream consumers don't see only "MH".
    if not address["state"] and address["state_code"]:
        full_name = _STATE_CODE_TO_NAME.get(address["state_code"].upper())
        if full_name:
            address["state"] = full_name

    if not address["postal_code"]:
        address["postal_code"] = _extract_postal("\n".join(lines))

    return address


def _extract_parties(text: str, addresses: dict[str, dict[str, str]]) -> dict[str, Party]:
    billing = addresses.get("billing", _empty_address())
    receiver = addresses.get("receiver_billing", _empty_address())

    vendor = Party(
        name=billing.get("name", ""),
        gstin=billing.get("gstin", ""),
        pan=billing.get("pan", ""),
        address=_format_address(billing),
    )
    customer = Party(
        name=receiver.get("name", ""),
        gstin=receiver.get("gstin", ""),
        pan=receiver.get("pan", ""),
        address=_format_address(receiver),
    )

    # The vendor PAN is often only present in the document footer (e.g.
    # "Registered office: ... PAN: AAJCC9783E ..."). When the billing block
    # didn't expose a PAN, scrape it from the footer.
    #
    # NB: we deliberately match the bare ``PAN:`` form (no "No" word) — the
    # *receiver* address block sometimes carries its own ``PAN No: ...``
    # line (ETRADE format) which would otherwise be picked up as the
    # vendor's PAN, swapping the parties.
    if not vendor.pan:
        pan_match = re.search(
            r"\bPAN\s*:\s*([A-Z]{5}\d{4}[A-Z])\b",
            text,
        )
        if pan_match:
            vendor.pan = pan_match.group(1)

    if not vendor.name:
        gstins = GSTIN_RE.findall(text)
        vendor.gstin = gstins[0] if gstins else ""
        customer.gstin = gstins[1] if len(gstins) > 1 else customer.gstin

    return {"vendor": vendor, "customer": customer}


def _format_address(addr: dict[str, str]) -> str:
    """Build a single-line display address.

    The ``address`` field already contains the full multi-line street block
    (which usually includes city/state/pin). Just append city/state/postal/
    country only if they aren't already substrings of the raw address, so we
    don't duplicate them."""
    raw = (addr.get("address") or "").strip()
    raw_lower = raw.lower()
    parts = [raw]
    for key in ("city", "state", "postal_code", "country"):
        value = (addr.get(key) or "").strip()
        if value and value.lower() not in raw_lower:
            parts.append(value)
    return ", ".join(p for p in parts if p)


def _extract_tax_summary(text: str) -> dict[str, float]:
    summary = {"cgst": 0.0, "sgst": 0.0, "igst": 0.0, "cess": 0.0, "tcs": 0.0, "tds": 0.0}

    # ETRADE footer: "Subtotal for 1,013.64" (total tax, often negative on credit notes).
    subtotal_for = re.search(r"Subtotal\s+for\s+(-?[\d,]+\.\d{2})", text, re.I)
    if subtotal_for:
        summary["igst"] = _to_float(subtotal_for.group(1))
        return summary

    # Clicktech / mixed-rate footer: sum "Sub Total : For IGST 15.01" lines.
    component_totals = {"igst": 0.0, "cgst": 0.0, "sgst": 0.0, "cess": 0.0}
    for match in re.finditer(
        r"(?:Sub\s*Total\s*:?\s*)?For\s+(IGST|CGST|SGST|CESS)\s+(-?[\d,]+\.\d{2})",
        text,
        re.I,
    ):
        key = match.group(1).lower()
        if key in component_totals:
            component_totals[key] += _to_float(match.group(2))

    if any(abs(v) >= 0.01 for v in component_totals.values()):
        for key, value in component_totals.items():
            summary[key] = round(value, 2)
        return summary

    # Last resort: footer lines only (avoid matching inline "IGST 55.21" in table rows).
    for key in summary:
        match = re.search(rf"(?:^|\n)\s*{key}\s*[:\-@]?\s*(-?[\d,]+\.\d{{2}})", text, re.I)
        if match:
            summary[key] = _to_float(match.group(1))
    return summary


def _extract_invoice_tax_total(text: str) -> float:
    subtotal_for = re.search(r"Subtotal\s+for\s+(-?[\d,]+\.\d{2})", text, re.I)
    if subtotal_for:
        return _to_float(subtotal_for.group(1))

    total = 0.0
    found = False
    for match in re.finditer(
        r"(?:Sub\s*Total\s*:?\s*)?For\s+(?:IGST|CGST|SGST|CESS)\s+(-?[\d,]+\.\d{2})",
        text,
        re.I,
    ):
        total += _to_float(match.group(1))
        found = True
    if found and abs(total) >= 0.01:
        return round(total, 2)

    # Clicktech consolidated tax subtotal after per-rate "For IGST" breakdown lines.
    if re.search(r"For\s+(?:IGST|CGST|SGST)", text, re.I):
        for match in reversed(list(re.finditer(r"Sub\s*Total:\s+(-?[\d,]+\.\d{2})", text, re.I))):
            before = text[max(0, match.start() - 40): match.start()]
            if re.search(r"For\s+(?:IGST|CGST|SGST)\s*$", before, re.I):
                continue
            return _to_float(match.group(1))

    match = re.search(r"total\s*tax\s*[:\-]?\s*(-?[\d,]+\.\d{2})", text, re.I)
    if match:
        return _to_float(match.group(1))

    return 0.0


def _reconcile_tax_totals(
    totals: dict[str, float],
    tax_summary: dict[str, float],
    line_items: list[LineItem],
) -> None:
    """When line amounts reconcile with the invoice total, trust summed line tax."""
    if not line_items:
        return

    line_tax = round(sum(float(item.tax_amount or 0) for item in line_items), 2)
    line_total = round(sum(float(item.total_amount or 0) for item in line_items), 2)
    grand = round(float(totals.get("grand_total") or 0), 2)
    invoice_tax = round(float(totals.get("tax_total") or 0), 2)

    if not grand or abs(line_total - grand) > 1.0:
        return

    if line_tax and abs(line_tax - invoice_tax) > 1.0:
        totals["tax_total"] = line_tax
        summary_sum = round(sum(tax_summary.values()), 2)
        if abs(summary_sum - invoice_tax) <= 1.0 or tax_summary.get("igst"):
            tax_summary["igst"] = line_tax
            for key in ("cgst", "sgst", "cess", "tcs", "tds"):
                if key != "igst" and abs(tax_summary.get(key, 0)) < 0.01:
                    tax_summary[key] = 0.0

    line_net = round(sum(float(item.total_cost or 0) for item in line_items), 2)
    if line_net and grand and abs(line_total - grand) <= 1.0:
        totals["subtotal"] = line_net


def _extract_totals(text: str) -> dict[str, float]:
    totals = {"subtotal": 0.0, "tax_total": 0.0, "grand_total": 0.0}
    patterns = {
        "subtotal": [r"sub[\s\-]?total\s*[:\-]?\s*(-?[\d,]+\.\d{2})", r"taxable\s*value\s*[:\-]?\s*(-?[\d,]+\.\d{2})"],
        "grand_total": [
            r"grand\s*total\s*[:\-]?\s*(-?[\d,]+\.\d{2})",
            # Reject both "Sub Total: X" (Clicktech) AND "Subtotal: X" (ETRADE)
            # via two negative lookbehinds that differ only in width.
            r"(?<![A-Za-z])(?<!Sub\s)Total:\s*(-?[\d,]+\.\d{2})",
            r"total\s*amount\s*[:\-]?\s*(-?[\d,]+\.\d{2})",
            r"net\s*amount\s*[:\-]?\s*(-?[\d,]+\.\d{2})",
        ],
    }
    for field, field_patterns in patterns.items():
        for pattern in field_patterns:
            match = re.search(pattern, text, re.I)
            if match:
                totals[field] = _to_float(match.group(1))
                break

    totals["tax_total"] = _extract_invoice_tax_total(text)
    if totals["tax_total"] == 0.0:
        tax_summary = _extract_tax_summary(text)
        totals["tax_total"] = round(sum(tax_summary.values()), 2)

    return totals


def _description_column_index(mapping: dict[str, int], row: list[str]) -> int | None:
    index = mapping.get("description")
    if index is not None:
        return index
    sl_idx = mapping.get("sl_no")
    if sl_idx is not None and sl_idx + 1 < len(row):
        return sl_idx + 1
    if len(row) > 1:
        return 1
    return None


def _recover_trailing_total(row: list[str], mapping: dict[str, int]) -> float:
    """When the mapped total cell is empty/dash, read the last plausible amount in the row."""
    idx = mapping.get("total_amount")
    if idx is not None and idx < len(row):
        direct = _to_float(row[idx])
        if direct != 0:
            return direct

    best = 0.0
    for cell in row[-6:]:
        val = _to_float(cell)
        if abs(val) >= abs(best) and abs(val) >= 1:
            best = val
    return best


def _extract_line_items(
    pages: list[RawPage],
    header: dict[str, str],
    doc_type: DocumentType,
    vendor: Party,
) -> list[LineItem]:
    items: list[LineItem] = []
    seen: set[str] = set()
    full_text = "\n".join(page.raw_text for page in pages)
    clicktech_credit = _is_clicktech_credit_document(doc_type, vendor, full_text)
    mapping_correction_logged = False

    # Cache the most-recent successful column mapping across pages. ETRADE
    # PDFs print the column header row only on page 1; pages 2-N continue
    # directly with item rows. Without this cache those pages would be
    # silently skipped because their "row 0" is not a header.
    last_mapping: dict[str, int] = {}
    last_raw_row: list[str] | None = None

    for page in pages:
        for table in page.tables:
            rows = table.get("rows", [])
            if len(rows) < 1:
                continue
            mapping = _map_columns(rows[0])
            data_rows: list[list[str]]
            if mapping:
                if clicktech_credit:
                    sample = rows[1] if len(rows) > 1 else None
                    mapping, corrected = _correct_clicktech_credit_mapping(mapping, sample)
                    if corrected and not mapping_correction_logged:
                        logging.info(
                            "Clicktech credit note column shift detected and corrected on page %s",
                            page.page_number,
                        )
                        mapping_correction_logged = True
                last_mapping = mapping
                data_rows = rows[1:]
            elif last_mapping:
                mapping = last_mapping
                data_rows = rows
            else:
                continue
            for row in data_rows:
                is_cont = _is_page_continuation_row(row, mapping)

                # 17-box rule: empty Sl. No. on page 2+ → join column-by-column into last row.
                if is_cont and last_raw_row is not None and items:
                    head_sl = _row_serial_number(last_raw_row, mapping)
                    merged_row = _merge_continuation_rows(last_raw_row, row, mapping)
                    merged_item = _row_to_line_item(
                        merged_row,
                        mapping,
                        header,
                        page.page_number,
                        clicktech_credit=clicktech_credit,
                        prepared=True,
                    )
                    if merged_item:
                        if head_sl and not (merged_item.system_ref_no or "").strip():
                            merged_item = merged_item.model_copy(
                                update={"system_ref_no": head_sl}
                            )
                        items[-1] = _sanitize_continuation_item(merged_item)
                        last_raw_row = merged_row
                        continue

                if items and is_cont:
                    shifted = _build_shifted_continuation_item(
                        row, mapping, page.page_number, items[-1]
                    )
                    if shifted and _apply_page_break_merge(
                        items, row, mapping, page.page_number, shifted
                    ):
                        continue
                if _try_merge_description_only_row(items, row, mapping, page.page_number):
                    continue
                prepared_row = _prepare_table_row(row, mapping)
                item = _row_to_line_item(
                    prepared_row,
                    mapping,
                    header,
                    page.page_number,
                    clicktech_credit=clicktech_credit,
                    prepared=True,
                )
                if not item:
                    continue
                item = _sanitize_continuation_item(item)
                if _apply_page_break_merge(items, row, mapping, page.page_number, item):
                    if last_raw_row is not None and items:
                        last_raw_row = prepared_row
                    continue
                if _is_summary_polluted_line_item(item):
                    continue
                if _is_duplicate_serial_number(items, item):
                    continue
                if _is_immediate_reprint_duplicate(items, item, page.page_number):
                    continue
                if _is_page2_reprint_duplicate(items, item, page.page_number):
                    continue
                # Two rows are the same line item only if every business identifier
                # also matches. Vendor invoice no, vendor invoice date, ASIN, EAN
                # and PO are what make rows with the same product/qty/total
                # genuinely distinct (e.g. same SKU returned in two PO batches).
                # The Sl./row number is included so that a Credit Note with
                # multiple visually-identical rows (same SKU repeated) is
                # preserved as separate items.
                key = "|".join(
                    [
                        item.system_ref_no,
                        item.product,
                        item.sku,
                        item.hsn,
                        item.asin,
                        item.ean,
                        item.combo,
                        item.invoice_no,
                        item.invoice_date,
                        str(item.quantity),
                        str(item.total_amount),
                    ]
                )
                if key in seen:
                    continue
                seen.add(key)
                items.append(item)
                last_raw_row = prepared_row

    if not items:
        items = _extract_line_items_from_text("\n".join(p.raw_text for p in pages), header)
    else:
        if doc_type == DocumentType.credit_note:
            items = [_apply_credit_note_signs(it) for it in items]
        items = _consolidate_page_break_items(items, "\n".join(p.raw_text for p in pages))

    return items


def _apply_credit_note_signs(item: LineItem) -> LineItem:
    """Credit note PDFs sometimes drop the minus on split-row totals while tax stays negative."""
    updates: dict[str, Any] = {}
    if item.total_amount > 0 and item.tax_amount < 0:
        updates["total_amount"] = -abs(item.total_amount)
    if item.total_cost > 0 and (item.tax_amount < 0 or (updates.get("total_amount", item.total_amount) < 0)):
        updates["total_cost"] = -abs(item.total_cost)
    if item.cost_per_unit > 0 and (updates.get("total_amount", item.total_amount) < 0 or item.tax_amount < 0):
        updates["cost_per_unit"] = -abs(item.cost_per_unit)
    return item.model_copy(update=updates) if updates else item


def _is_clicktech_credit_document(doc_type: DocumentType, vendor: Party, text: str) -> bool:
    """Clicktech GST Credit Note and Cancellation share a table layout unlike GST Invoice."""
    if doc_type != DocumentType.credit_note:
        return False
    haystack = f"{vendor.name} {vendor.gstin} {vendor.pan} {text[:3000]}".lower()
    return "clicktech" in haystack or "aajcc9783e" in haystack


def _looks_like_clicktech_vendor_invoice(value: str) -> bool:
    cleaned = _clean_cell(value)
    if not cleaned:
        return False
    return "/" in cleaned or bool(re.match(r"^CKD/", cleaned, re.I))


def _looks_like_clicktech_po(value: str) -> bool:
    code = _clean_code(value)
    if not code or "/" in code:
        return False
    if GSTIN_RE.fullmatch(code) or _ASIN_RE.match(code):
        return False
    return 4 <= len(code) <= 12 and bool(re.match(r"^[A-Z0-9]+$", code, re.I))


def _shift_mapping_from(mapping: dict[str, int], start_field: str, delta: int) -> None:
    start_idx = mapping.get(start_field)
    if start_idx is None:
        return
    for field in (
        "purchase_order_no",
        "vendor_invoice_no",
        "vendor_invoice_date",
        "unit_code",
        "quantity",
        "rate",
        "taxable_value",
        "tax_rate",
        "tax_type",
        "tax_amount",
        "total_amount",
    ):
        idx = mapping.get(field)
        if idx is not None and idx >= start_idx:
            mapping[field] = idx + delta


def _correct_clicktech_credit_mapping(
    mapping: dict[str, int],
    sample_row: list[str] | None,
) -> tuple[dict[str, int], bool]:
    """Fix header/data mis-alignment on Clicktech credit note and cancellation tables."""
    corrected = dict(mapping)
    changed = False

    po_idx = corrected.get("purchase_order_no")
    ven_idx = corrected.get("vendor_invoice_no")
    date_idx = corrected.get("vendor_invoice_date")
    if po_idx is not None and ven_idx is not None and date_idx is not None:
        if ven_idx - po_idx != 1 or date_idx - ven_idx != 1:
            _shift_mapping_from(corrected, "purchase_order_no", -1)
            changed = True

    if sample_row and po_idx is not None and po_idx < len(sample_row):
        po_val = _clean_code(sample_row[corrected.get("purchase_order_no", po_idx)])
        if _looks_like_clicktech_vendor_invoice(po_val) and not _looks_like_clicktech_po(po_val):
            _shift_mapping_from(corrected, "purchase_order_no", -1)
            changed = True

    return corrected, changed


def _normalize_header(cell: str) -> tuple[str, str]:
    spaced = re.sub(r"\s+", " ", cell.lower().replace("\n", " ")).strip()
    compact = spaced.replace(" ", "")
    return spaced, compact


def _map_columns(header_row: list[str]) -> dict[str, int]:
    headers = [_normalize_header(cell) for cell in header_row]
    mapping: dict[str, int] = {}
    used: set[int] = set()

    for field, matcher in COLUMN_RULES:
        for index, (spaced, compact) in enumerate(headers):
            if index in used:
                continue
            if matcher(spaced, compact):
                mapping[field] = index
                used.add(index)
                break

    if "description" not in mapping and "total_amount" not in mapping and "taxable_value" not in mapping:
        return {}
    return mapping


def _looks_like_po_code(value: str) -> bool:
    code = _clean_code(value)
    if not code or "/" in code:
        return False
    if GSTIN_RE.fullmatch(code) or _ASIN_RE.match(code):
        return False
    return 3 <= len(code) <= 12 and bool(re.match(r"^[A-Z0-9]+$", code, re.I))


def _looks_like_asin_tail_fragment(value: str) -> bool:
    code = _clean_code(value)
    if not code or len(code) < 3:
        return False
    if _ASIN_RE.match(code) or code.startswith("B0"):
        return True
    return bool(re.match(r"^[A-Z0-9]{3,8}$", code, re.I)) and not code.isdigit()


def _realign_page_break_row(row: list[str], mapping: dict[str, int]) -> list[str]:
    """Remove spurious empty columns on page-break tail rows so fields stay aligned."""
    if not row or not mapping:
        return row
    expected_len = max(mapping.values()) + 1
    if len(row) != expected_len + 1:
        return row

    sl_idx = mapping.get("sl_no", 0)
    if sl_idx < len(row) and _clean_cell(row[sl_idx]):
        return row

    asin_idx = mapping.get("asin")
    ean_idx = mapping.get("ean")
    po_idx = mapping.get("purchase_order_no")
    if asin_idx is None:
        return row

    asin_cell = (row[asin_idx] or "").strip() if asin_idx < len(row) else ""
    if not asin_cell and asin_idx + 1 < len(row):
        next_cell = _clean_code(row[asin_idx + 1])
        if _ASIN_RE.match(next_cell):
            return row[:asin_idx] + row[asin_idx + 1:]

    if ean_idx is not None and po_idx is not None and po_idx < len(row):
        po_cell = _clean_code(row[po_idx])
        if not _looks_like_po_code(po_cell):
            ven_idx = mapping.get("vendor_invoice_no")
            start = (ean_idx if ean_idx is not None else asin_idx) + 1
            for remove_idx in range(start, min(po_idx + 3, len(row))):
                if remove_idx >= len(row) or (row[remove_idx] or "").strip():
                    continue
                trial = row[:remove_idx] + row[remove_idx + 1:]
                if len(trial) != expected_len:
                    continue
                trial_po = _clean_code(trial[po_idx]) if po_idx < len(trial) else ""
                trial_ven = _clean_cell(trial[ven_idx]) if ven_idx is not None and ven_idx < len(trial) else ""
                if _looks_like_po_code(trial_po) and ("/" in trial_ven or re.search(r"\d", trial_ven)):
                    return trial

    return row


def _recover_vendor_invoice_no(row: list[str], mapping: dict[str, int]) -> str:
    """Find vendor invoice number in the correct column or any shifted cell."""
    idx = mapping.get("vendor_invoice_no")
    if idx is not None and idx < len(row):
        val = re.sub(r"\s+", "", _clean_cell(row[idx]))
        if re.search(r"(?:ETD|CKD|CTDF)/", val, re.I):
            return val

    for raw in row:
        val = _strip_summary_suffix(re.sub(r"\s+", "", _clean_cell(raw)))
        if re.search(r"(?:ETD|CKD|CTDF)/", val, re.I) and len(val) >= 8:
            return val
    return ""


def _recover_tax_rate(row: list[str], mapping: dict[str, int], quantity: float) -> float:
    """Pick a valid GST % from the mapped column or nearby numeric cells."""
    idx = mapping.get("tax_rate")
    if idx is not None and idx < len(row):
        val = _to_number(row[idx])
        if val in (5.0, 12.0, 18.0, 28.0):
            return val

    center = mapping.get("tax_rate", mapping.get("taxable_value", len(row) - 4))
    for offset in range(-2, 4):
        idx = center + offset
        if 0 <= idx < len(row):
            val = _to_number(row[idx])
            if val in (5.0, 12.0, 18.0, 28.0) and val != quantity:
                return val
    return 0.0


def _prepare_table_row(row: list[str], mapping: dict[str, int]) -> list[str]:
    """Align a raw pdfplumber row to the header column count (~17 boxes)."""
    row = list(row)
    is_cont = _is_page_continuation_row(row, mapping)
    expected_len = (max(mapping.values()) + 1) if mapping else len(row)
    if len(row) > expected_len:
        row = _normalize_table_row(row, mapping, continuation=is_cont)
    row = _realign_page_break_row(row, mapping)
    asin_idx = mapping.get("asin")
    if asin_idx is not None and len(row) == expected_len + 1 and asin_idx + 1 < len(row):
        asin_cell = (row[asin_idx] or "").strip()
        next_cell = re.sub(r"\s+", "", (row[asin_idx + 1] or "").strip())
        if not asin_cell and _ASIN_RE.match(next_cell):
            row = row[:asin_idx] + row[asin_idx + 1:]
    return _normalize_table_row(row, mapping, continuation=is_cont)


def _is_partial_page_head_row(row: list[str], mapping: dict[str, int]) -> bool:
    """True when page N ends mid-row: has Sl. No. but totals/ASIN finish on page N+1."""
    sl = _row_serial_number(row, mapping)
    if not sl or _is_page_continuation_row(row, mapping):
        return False
    desc = _row_description(row, mapping)
    if not desc.strip():
        return False

    total_idx = mapping.get("total_amount")
    total = abs(_to_float(row[total_idx] if total_idx is not None and total_idx < len(row) else ""))
    qty_idx = mapping.get("quantity")
    qty = abs(_to_float(row[qty_idx] if qty_idx is not None and qty_idx < len(row) else ""))
    asin_idx = mapping.get("asin")
    asin = _clean_code(row[asin_idx] if asin_idx is not None and asin_idx < len(row) else "")

    if total >= 0.01 and qty >= 0.01 and _ASIN_RE.match(asin) and len(desc) >= 20:
        return False
    return len(desc) < 45 or not _ASIN_RE.match(asin) or total < 0.01


def _row_to_line_item(
    row: list[str],
    mapping: dict[str, int],
    header: dict[str, str],
    page_number: int,
    *,
    clicktech_credit: bool = False,
    prepared: bool = False,
) -> LineItem | None:
    row = list(row) if prepared else _prepare_table_row(row, mapping)
    sl_no_val = ""
    if mapping.get("sl_no") is not None and mapping["sl_no"] < len(row):
        sl_no_val = _clean_cell(row[mapping["sl_no"]])

    def cell(field: str) -> str:
        index = mapping.get(field)
        if field == "description" and index is None:
            index = _description_column_index(mapping, row)
        if index is None or index >= len(row):
            return ""
        return row[index].strip()

    product = _clean_product(cell("description"))
    if _is_summary_row(product):
        return None

    if not sl_no_val:
        sl_no_val = _clean_cell(cell("sl_no"))
    quantity = _to_number(cell("quantity"))
    rate = _to_float(cell("rate"))
    taxable_value = _to_float(cell("taxable_value"))
    total_amount = _to_float(cell("total_amount"))
    # Misaligned split rows sometimes put rate in the qty column (negative qty).
    if quantity <= 0 and sl_no_val:
        qty_idx = mapping.get("quantity")
        for idx in range(max(0, (qty_idx or 0) - 1), min(len(row), (qty_idx or 0) + 4)):
            val = _to_number(row[idx])
            if 0 < val <= 10_000 and abs(val - round(val)) < 0.001:
                quantity = val
                break
    # Only recover misaligned totals on page-break continuation rows (no serial no).
    if total_amount == 0.0 and not sl_no_val:
        total_amount = _recover_trailing_total(row, mapping)
    elif sl_no_val and abs(total_amount) <= 28 and abs(total_amount) in {5.0, 12.0, 18.0, 28.0}:
        recovered = _recover_trailing_total(row, mapping)
        if abs(recovered) > abs(total_amount):
            total_amount = recovered
    tax_amount = _to_float(cell("tax_amount"))
    tax_rate = _recover_tax_rate(row, mapping, quantity)

    if quantity == 0.0 and rate > 0:
        if taxable_value > 0:
            quantity = round(taxable_value / rate)
        elif total_amount > 0:
            quantity = max(1.0, round(total_amount / rate))

    if total_amount == 0.0 and taxable_value > 0:
        total_amount = taxable_value
    if total_amount == 0.0 and quantity and rate:
        total_amount = round(quantity * rate, 2)

    if not product and total_amount == 0.0 and taxable_value == 0.0:
        return None

    if not product.strip() and quantity == 0.0:
        return None

    vendor_invoice_no = _clean_cell(cell("vendor_invoice_no"))
    if vendor_invoice_no:
        vendor_invoice_no = _strip_summary_suffix(re.sub(r"\s+", "", vendor_invoice_no))
    if not re.search(r"(?:ETD|CKD|CTDF)/", vendor_invoice_no or "", re.I):
        recovered = _recover_vendor_invoice_no(row, mapping)
        if recovered:
            vendor_invoice_no = recovered
    vendor_invoice_date = _clean_cell(cell("vendor_invoice_date"))
    asin_val = _clean_code(cell("asin"))
    ean_val = _clean_code(cell("ean"))
    sku_val = _clean_code(cell("sku"))
    hsn_val = _clean_code(cell("hsn"))
    combo_val = _clean_po_code(cell("purchase_order_no"))
    return_id_val = _clean_code(cell("return_id"))
    shipment_id_val = _clean_code(cell("shipment_id"))

    # Clicktech GST Credit Note / Cancellation prints the customer GSTIN in the
    # UPC/EAN column — there is no real EAN. Do NOT run the column-shift logic
    # that was written for a different layout where GSTIN was an extra column.
    if ean_val and (
        GSTIN_RE.fullmatch(ean_val) or (clicktech_credit and _looks_like_gstin_fragment(ean_val))
    ):
        if clicktech_credit:
            ean_val = ""
        else:
            ean_val = _clean_code(cell("purchase_order_no"))
            combo_val = _clean_code(cell("vendor_invoice_no"))
            vendor_invoice_no = _clean_cell(cell("vendor_invoice_date"))
            vendor_invoice_date = ""

    # Reject continuation rows: pdfplumber sometimes emits a stray row that
    # only contains the wrapped tail of the previous item's description, with
    # every numeric column empty and only short, fragmented identifier strings
    # (e.g. ``vendor_invoice_no="97"`` or ``asin="S"`` from a 4-line wrap).
    # An identifier counts only when it's at least 4 chars — long enough to
    # NOT be a wrap fragment, short enough not to reject any real ETRADE /
    # Clicktech ID format.
    has_numeric = any(
        v != 0 for v in (quantity, rate, taxable_value, total_amount, tax_amount)
    )
    has_identifier = any(
        len(v) >= 4
        for v in (vendor_invoice_no, asin_val, ean_val, sku_val, hsn_val)
        if v
    )
    if not has_numeric and not has_identifier:
        if _is_page_continuation_row(row, mapping):
            frag = any(
                len(_clean_code(cell(f)) or "") >= 2
                for f in (
                    "asin",
                    "ean",
                    "sku",
                    "hsn",
                    "purchase_order_no",
                    "vendor_invoice_no",
                    "return_id",
                    "shipment_id",
                )
            )
            if frag or product.strip():
                pass
            else:
                return None
        elif sl_no_val and product.strip() and _is_partial_page_head_row(row, mapping):
            pass
        else:
            return None

    if _is_summary_polluted_line_item(
        LineItem(
            product=product,
            combo=combo_val,
            invoice_no=vendor_invoice_no,
            hsn=hsn_val,
            asin=asin_val,
        )
    ):
        return None

    return LineItem(
        system_ref_no=_clean_cell(cell("sl_no")),
        invoice_no=vendor_invoice_no or header.get("invoice_number", ""),
        invoice_date=vendor_invoice_date or header.get("invoice_date", ""),
        combo=combo_val,
        document_number=header.get("document_number", ""),
        document_date=header.get("document_date", ""),
        product=product,
        sku=sku_val,
        ean=ean_val,
        hsn=hsn_val,
        asin=asin_val,
        units=_clean_cell(cell("unit_code")),
        quantity=quantity,
        cost_per_unit=rate,
        total_cost=taxable_value,
        tax_type=_clean_cell(cell("tax_type")),
        tax_rate=tax_rate,
        tax_amount=tax_amount,
        total_amount=total_amount,
        return_id=return_id_val,
        shipment_id=shipment_id_val,
        source_ref={"page": page_number, "confidence": 0.8},
    )


def _extract_line_items_from_text(text: str, header: dict[str, str]) -> list[LineItem]:
    items: list[LineItem] = []
    for line in text.splitlines():
        if not AMOUNT_RE.search(line):
            continue
        parts = re.split(r"\s{2,}|\t", line.strip())
        if len(parts) < 2:
            continue
        amount = _to_float(AMOUNT_RE.findall(line)[-1])
        product = parts[0]
        if len(product) < 3 or amount <= 0:
            continue
        items.append(
            LineItem(
                invoice_no=header.get("invoice_number", ""),
                invoice_date=header.get("invoice_date", ""),
                document_number=header.get("document_number", ""),
                document_date=header.get("document_date", ""),
                product=product[:200],
                total_amount=amount,
                source_ref={"page": 1, "confidence": 0.5},
            )
        )
    return items[:100]


def _clean_cell(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\n", " ")).strip()


def _clean_code(value: str) -> str:
    """Join wrapped code/identifier cells (ASIN, EAN, HSN, SKU, PO) with no
    whitespace at all.

    pdfplumber returns multi-line cells like ``"B0BH8\nSNV12"`` or
    ``"89044\n57617\n106"`` because the column is narrow. For codes we want
    a single contiguous token (``"B0BH8SNV12"`` / ``"8904457617106"``)
    rather than a space-joined string."""
    if not value:
        return ""
    return re.sub(r"\s+", "", value)


def _clean_product(value: str) -> str:
    text = _clean_cell(value)
    # Split rows sometimes leak price/qty fragments into the description column.
    text = re.sub(r"^[\s\-]*(?:\d[\d,]*\.\d{2}\s*)+[\-\s]*", "", text).strip()
    text = re.sub(r"^-\s*-?\s*", "", text).strip()
    return text


def _is_summary_row(product: str) -> bool:
    lowered = product.lower()
    return any(
        phrase in lowered
        for phrase in ("sub total", "subtotal", "grand total", "total qty", "for igst", "for cgst")
    )


def _to_number(value: str) -> float:
    if not value:
        return 0.0
    # Numeric cells in narrow PDF columns sometimes wrap mid-number, e.g.
    # ``"18309.5\n2"`` actually means ``18309.52``. Strip ALL whitespace
    # (newlines, spaces, tabs) before parsing, not just trim the ends.
    cleaned = re.sub(r"\s+", "", value).replace(",", "")
    if not cleaned:
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        match = re.search(r"\d+(?:\.\d+)?", cleaned)
        return float(match.group()) if match else 0.0


def _to_float(value: str) -> float:
    return _to_number(value)
