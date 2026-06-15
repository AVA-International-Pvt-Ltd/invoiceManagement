"""Scan all stored documents for page-break split issues."""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.extractors import parse_document, read_document
from app.job_summary import detect_document_subtype, detect_source
from app.storage import EXTRACTIONS_DIR, UPLOAD_DIR

ASIN_RE = re.compile(r"^B0[A-Z0-9]{8}$", re.I)
PARTIAL_ASIN_RE = re.compile(r"^B0[A-Z0-9]{1,9}$", re.I)
PAGE_RE = re.compile(r"Page\s+(\d+)\s+of\s+(\d+)", re.I)
TOTAL_QTY_RE = re.compile(r"Total Qty:\s*(\d+(?:\.\d+)?)", re.I)
GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z]\d[Z][A-Z\d]$", re.I)


def find_pdf(stored: dict) -> Path | None:
    document = stored.get("document") or {}
    audit = document.get("audit") or {}
    candidate = audit.get("source_uri")
    if candidate:
        path = Path(candidate)
        if path.is_file():
            return path
    file_name = audit.get("file_name")
    if file_name:
        path = UPLOAD_DIR / file_name
        if path.is_file():
            return path
    return None


def hsn_digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def page_count(text: str) -> int:
    m = PAGE_RE.search(text)
    return int(m.group(2)) if m else 1


def scan_item_issues(items: list, text: str) -> list[dict]:
    issues: list[dict] = []
    for idx, item in enumerate(items, 1):
        asin = (item.asin or "").strip()
        hsn = item.hsn or ""
        hsn_d = hsn_digits(hsn)
        ean = (item.ean or "").strip()
        product = (item.product or "").strip()
        page = (item.source_ref.page if item.source_ref else None) or 0

        if asin and asin.startswith("B0") and not ASIN_RE.match(asin):
            issues.append(
                {
                    "type": "partial_asin",
                    "item": idx,
                    "field": "asin",
                    "value": asin,
                    "page": page,
                    "product_snippet": product[:70],
                }
            )

        if hsn_d and 0 < len(hsn_d) < 6:
            issues.append(
                {
                    "type": "partial_hsn",
                    "item": idx,
                    "field": "hsn",
                    "value": hsn,
                    "page": page,
                    "product_snippet": product[:70],
                }
            )

        if ean and GSTIN_RE.match(ean):
            issues.append(
                {
                    "type": "gstin_in_ean",
                    "item": idx,
                    "field": "ean",
                    "value": ean,
                    "page": page,
                    "product_snippet": product[:70],
                }
            )

        if ean and len(ean) <= 11 and ean.startswith("07AAT"):
            issues.append(
                {
                    "type": "partial_gstin_in_ean",
                    "item": idx,
                    "field": "ean",
                    "value": ean,
                    "page": page,
                    "product_snippet": product[:70],
                }
            )

        if product and len(product) > 20 and product.endswith("-") or (
            product and len(product) > 40 and not asin and not hsn_d
        ):
            pass  # too noisy

    for i in range(1, len(items)):
        prev, cur = items[i - 1], items[i]
        pp = (prev.source_ref.page if prev.source_ref else 0) or 0
        cp = (cur.source_ref.page if cur.source_ref else 0) or 0
        if cp > pp and not (cur.system_ref_no or "").strip():
            issues.append(
                {
                    "type": "possible_unmerged_tail",
                    "item": i + 1,
                    "field": "row",
                    "value": f"page {pp}->{cp}, sl_no empty",
                    "page": cp,
                    "product_snippet": (cur.product or cur.asin or "")[:70],
                }
            )

    qty_match = TOTAL_QTY_RE.search(text)
    if qty_match and items:
        exp = float(qty_match.group(1))
        got = sum(float(it.quantity or 0) for it in items)
        if abs(exp - got) > 0.01:
            issues.append(
                {
                    "type": "qty_mismatch",
                    "item": 0,
                    "field": "quantity",
                    "value": f"PDF Total Qty={exp:g}, extracted sum={got:g}",
                    "page": 0,
                    "product_snippet": "",
                }
            )

    return issues


def scan_raw_page_splits(pages_text: list[str]) -> list[dict]:
    """Detect continuation-like raw table patterns from stored raw text."""
    hints: list[dict] = []
    full = "\n".join(pages_text)
    if page_count(full) <= 1:
        return hints

    for pi, page_text in enumerate(pages_text, 1):
        if pi == 1:
            continue
        lines = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
        for ln in lines[:15]:
            lowered = ln.lower()
            if any(x in lowered for x in ("sub total", "subtotal", "grand total", "total qty")):
                continue
            # Row starting without digit sl_no but with product-ish text
            if re.match(r"^[A-Za-z]", ln) and not re.match(r"^(Sl\.|SI\.|Page|GST|Billing|Shipping)", ln, re.I):
                if PARTIAL_ASIN_RE.search(re.sub(r"\s+", "", ln)) or len(ln) > 30:
                    hints.append(
                        {
                            "type": "page2_text_continuation",
                            "item": 0,
                            "field": "raw_text",
                            "value": ln[:80],
                            "page": pi,
                            "product_snippet": ln[:70],
                        }
                    )
                    break
    return hints


def main() -> None:
    json_files = sorted(EXTRACTIONS_DIR.glob("*.json"))
    all_rows: list[dict] = []
    multi_page_total = 0
    with_issues = 0
    missing_pdf = 0

    for path in json_files:
        stored = json.loads(path.read_text(encoding="utf-8"))
        doc = stored.get("document") or {}
        audit = doc.get("audit") or {}
        header = doc.get("header") or {}
        file_name = audit.get("file_name", path.stem)
        vendor = doc.get("vendor") or {}
        source = detect_source(vendor.get("name", ""), vendor.get("gstin", ""), vendor.get("pan", ""))
        subtype = detect_document_subtype(
            doc.get("document_type", ""), header.get("reason", ""), file_name
        )

        pdf = find_pdf(stored)
        pages_text = [p.get("raw_text", "") for p in (doc.get("raw_data") or {}).get("pages", [])]
        pg_count = page_count("\n".join(pages_text))

        entry: dict = {
            "file_name": file_name,
            "job_id": path.stem,
            "source": source,
            "subtype": subtype,
            "pages": pg_count,
            "item_count": len(doc.get("line_items") or []),
            "issues": [],
            "status": "OK",
        }

        if pg_count > 1:
            multi_page_total += 1

        if pdf and pdf.is_file():
            try:
                parsed = parse_document(pdf.name, read_document(pdf))
                items = parsed["line_items"]
                text = "\n".join(p.raw_text for p in read_document(pdf))
                entry["item_count"] = len(items)
                entry["issues"] = scan_item_issues(items, text)
                if pg_count > 1:
                    entry["issues"].extend(scan_raw_page_splits(pages_text))
            except Exception as exc:
                entry["issues"] = [
                    {
                        "type": "parse_error",
                        "item": 0,
                        "field": "",
                        "value": str(exc),
                        "page": 0,
                        "product_snippet": "",
                    }
                ]
        else:
            missing_pdf += 1
            entry["status"] = "PDF missing"
            continue

        # De-dupe issue types per file
        seen = set()
        unique_issues = []
        for iss in entry["issues"]:
            key = (iss["type"], iss["item"], iss["field"], iss.get("value", ""))
            if key not in seen:
                seen.add(key)
                unique_issues.append(iss)
        entry["issues"] = unique_issues

        if entry["issues"]:
            with_issues += 1
            entry["status"] = "SPLIT / ISSUE DETECTED"
            all_rows.append(entry)

    report_path = Path(__file__).resolve().parent.parent / "data" / "page_split_audit.json"
    report_path.write_text(
        json.dumps(
            {
                "total_documents": len(json_files),
                "multi_page_documents": multi_page_total,
                "documents_with_split_issues": with_issues,
                "missing_pdf": missing_pdf,
                "flagged": all_rows,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print("=" * 80)
    print("PAGE-BREAK / SPLIT DATA AUDIT — ALL DOCUMENTS")
    print("=" * 80)
    print(f"Total documents scanned:     {len(json_files)}")
    print(f"Multi-page PDFs:             {multi_page_total}")
    print(f"Documents with split issues: {with_issues}")
    print(f"Clean (no split flags):      {len(json_files) - with_issues - missing_pdf}")
    print(f"Missing PDF:                 {missing_pdf}")
    print("=" * 80)

    if not all_rows:
        print("\nNo page-break split issues detected.")
        return

    by_type: dict[str, int] = {}
    for row in all_rows:
        for iss in row["issues"]:
            by_type[iss["type"]] = by_type.get(iss["type"], 0) + 1

    print("\nIssue types across flagged documents:")
    for t, c in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"  {t}: {c}")

    print(f"\n{'=' * 80}")
    print("FULL LIST — DOCUMENTS WITH PAGE-BREAK / SPLIT ISSUES")
    print("=" * 80)

    for row in sorted(all_rows, key=lambda r: r["file_name"]):
        print(f"\n📄 {row['file_name']}")
        print(f"   Source: {row['source']} | Type: {row['subtype']} | Pages: {row['pages']} | Items: {row['item_count']}")
        for iss in row["issues"]:
            item_label = f"Item {iss['item']}" if iss["item"] else "Document"
            page_label = f"page {iss['page']}" if iss["page"] else ""
            print(f"   • [{iss['type']}] {item_label} {page_label} — {iss['field']}: {iss['value']!r}")
            if iss.get("product_snippet"):
                print(f"     Product/text: {iss['product_snippet']!r}")

    print(f"\nFull JSON report: {report_path}")


if __name__ == "__main__":
    main()
