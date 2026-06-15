"""Generate QA report — run anytime to confirm 100% verified data.

Usage:
    python qa_report.py          # print report, exit 0 if all verified
    python qa_report.py --strict # same, exit 1 if any document is not verified
"""
from __future__ import annotations

import sys

from app.extraction_quality import scan_all_documents


def main() -> None:
    report = scan_all_documents()
    total = report["total"]
    verified = report["verified"]
    needs_review = report["needs_review"]
    failed = report["failed"]

    print("=" * 70)
    print("QA REPORT")
    print("=" * 70)
    print(f"Documents:      {total}")
    print(f"✓ Verified:     {verified} ({report['verified_percent']:.1f}%)")
    print(f"⚠ Review:       {needs_review} ({100 * needs_review / total:.1f}%)" if total else "⚠ Review:       0")
    print(f"✕ Unreliable:   {failed} ({100 * failed / total:.1f}%)" if total else "✕ Unreliable:   0")

    if report["not_verified"]:
        print("\nDocuments not verified:")
        for item in report["not_verified"]:
            issues = "; ".join(item["issues"]) if item["issues"] else item["status"]
            print(f"  - {item['file_name']}: {issues}")

    if report["all_verified"]:
        print("\n✓ ALL DOCUMENTS VERIFIED (100%)")
    else:
        print(f"\n✕ NOT 100% — {total - verified} document(s) need attention")

    print("=" * 70)

    if "--strict" in sys.argv or "-s" in sys.argv:
        sys.exit(0 if report["all_verified"] else 1)


if __name__ == "__main__":
    main()
