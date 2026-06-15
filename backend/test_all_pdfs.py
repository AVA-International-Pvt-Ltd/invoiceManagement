"""Regression test: run parser against every uploaded PDF and report
key metrics so we can spot regressions across all 12 files at once."""
from pathlib import Path

from app.extractors import parse_document, read_document

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"


def summarize(pdf: Path) -> dict:
    pages = read_document(pdf)
    parsed = parse_document(pdf.name, pages)
    items = parsed["line_items"]

    qty = sum(i.quantity for i in items)
    total = round(sum(i.total_amount for i in items), 2)
    grand_total = round(float(parsed["totals"].get("grand_total", 0.0)), 2)
    junk = sum(1 for i in items if i.quantity == 0 and i.total_amount == 0)
    spaces_in_codes = sum(
        1
        for i in items
        if " " in (i.asin or "") or " " in (i.ean or "") or " " in (i.combo or "")
    )

    invoice_keys = {
        (i.product, i.invoice_no, i.invoice_date, i.quantity, i.total_amount)
        for i in items
    }
    duplicates = len(items) - len(invoice_keys)

    return {
        "file": pdf.name,
        "pages": len(pages),
        "items": len(items),
        "qty_sum": qty,
        "total_sum": total,
        "grand_total": grand_total,
        "delta": round(total - grand_total, 2),
        "junk_rows": junk,
        "codes_with_spaces": spaces_in_codes,
        "duplicate_rows": duplicates,
    }


def main() -> None:
    pdfs = sorted(p for p in UPLOAD_DIR.glob("*.pdf"))
    print(
        f"{'File':<28} {'pg':>3} {'#items':>6} {'qty':>6} {'sum_total':>12} "
        f"{'grand':>10} {'Δ':>6} {'junk':>4} {'sp_codes':>8} {'dup':>4}"
    )
    print("-" * 110)
    issues = 0
    for pdf in pdfs:
        s = summarize(pdf)
        flag = ""
        if s["junk_rows"]:
            flag += " J"
            issues += 1
        if s["codes_with_spaces"]:
            flag += " S"
            issues += 1
        if s["duplicate_rows"]:
            flag += " D"
            issues += 1
        if abs(s["delta"]) > 1.0 and s["grand_total"] > 0:
            flag += " T"
        print(
            f"{s['file']:<28} {s['pages']:>3} {s['items']:>6} {s['qty_sum']:>6.0f} "
            f"{s['total_sum']:>12.2f} {s['grand_total']:>10.2f} {s['delta']:>6.2f} "
            f"{s['junk_rows']:>4} {s['codes_with_spaces']:>8} {s['duplicate_rows']:>4} "
            f"{flag}"
        )
    print("-" * 110)
    print(
        "Legend:  J=junk rows present, S=codes still have spaces, "
        "D=duplicate rows, T=line sum doesn't match grand total (>1)"
    )
    if issues == 0:
        print("\nALL CLEAN")
    else:
        print(f"\n{issues} flag(s) raised across files")


if __name__ == "__main__":
    main()
