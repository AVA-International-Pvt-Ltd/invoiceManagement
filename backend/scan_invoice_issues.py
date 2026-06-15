"""Scan all PDFs for vendor invoice truncation / merge issues."""
from __future__ import annotations

import re
from pathlib import Path

from app.extractors import parse_document, read_document
from app.profile_checks import VENDOR_INVOICE_RE

UPLOADS = Path(__file__).resolve().parent.parent / "data" / "uploads"


def suffix_len(inv: str) -> int:
    if "/" not in inv:
        return 0
    last = inv.rsplit("/", 1)[-1]
    return len(last) if last.isdigit() else 0


def scan_doc(fn: str) -> list[dict]:
    items = parse_document(fn, read_document(UPLOADS / fn))["line_items"]
    invs = [(i + 1, (it.invoice_no or "").strip()) for i, it in enumerate(items)]
    all_inv = [x for _, x in invs if x]
    issues: list[dict] = []

    for ln, inv in invs:
        if not inv:
            continue
        if not VENDOR_INVOICE_RE.match(inv):
            issues.append({"line": ln, "invoice": inv, "kind": "regex_fail"})
            continue
        for other in all_inv:
            if other != inv and other.startswith(inv) and len(other) > len(inv):
                issues.append(
                    {"line": ln, "invoice": inv, "kind": "truncated", "full": other}
                )
                break
        else:
            if re.match(r"(?i)(?:ETD|CKD)/\d{2}-\d{2}/\d+$", inv) and suffix_len(inv) < 4:
                issues.append({"line": ln, "invoice": inv, "kind": "short_suffix"})
            if re.match(r"(?i)ETD/DF/\d{2}$", inv):
                issues.append({"line": ln, "invoice": inv, "kind": "df_truncated"})
    return issues


def main() -> None:
    all_issues: list[tuple[str, list[dict]]] = []
    for pdf in sorted(UPLOADS.glob("*.pdf")):
        issues = scan_doc(pdf.name)
        if issues:
            all_issues.append((pdf.name, issues))

    print(f"Documents with invoice issues: {len(all_issues)} / {len(list(UPLOADS.glob('*.pdf')))}")
    for fn, issues in all_issues:
        print(f"\n{fn}:")
        for issue in issues:
            extra = f" -> {issue['full']}" if issue.get("full") else ""
            print(f"  line {issue['line']}: [{issue['kind']}] {issue['invoice']!r}{extra}")


if __name__ == "__main__":
    main()
