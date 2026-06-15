"""Re-parse flagged PDFs with current parser and compare to stored JSON."""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.extractors import parse_document, read_document
from app.models import NormalizedDocument
from app.storage import EXTRACTIONS_DIR, UPLOAD_DIR

ASIN_RE = re.compile(r"^B0[A-Z0-9]{8}$", re.I)
REPORT = Path(__file__).resolve().parent.parent / "data" / "deep_audit_report.json"


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


def flags_for_items(items) -> list[str]:
    out: list[str] = []
    for idx, item in enumerate(items, 1):
        asin = (item.asin or "").strip()
        if asin and asin.startswith("B0") and not ASIN_RE.match(asin):
            out.append(f"item {idx}: partial ASIN {asin!r}")
    return out


def main() -> None:
    if not REPORT.is_file():
        print("Run deep_audit.py first.")
        return

    report = json.loads(REPORT.read_text(encoding="utf-8"))
    flagged = report.get("flagged_files") or []
    by_name: dict[str, Path] = {}
    job_by_name: dict[str, str] = {}

    for path in EXTRACTIONS_DIR.glob("*.json"):
        stored = json.loads(path.read_text(encoding="utf-8"))
        doc = stored.get("document") or {}
        fn = doc.get("audit", {}).get("file_name", "")
        if fn:
            job_by_name[fn] = path.stem
            pdf = find_pdf(stored)
            if pdf:
                by_name[fn] = pdf

    print(f"Re-parsing {len(flagged)} flagged document(s) with current parser...\n")
    fixed = 0
    still_bad = 0
    missing_pdf = 0

    for file_name in sorted(flagged):
        pdf = by_name.get(file_name)
        if not pdf:
            missing_pdf += 1
            print(f"  SKIP (no PDF): {file_name}")
            continue

        job_id = job_by_name.get(file_name, "?")
        stored = json.loads((EXTRACTIONS_DIR / f"{job_id}.json").read_text(encoding="utf-8"))
        old_doc = NormalizedDocument.model_validate(stored["document"])
        new_doc = parse_document(pdf.name, read_document(pdf))
        new_items = new_doc["line_items"]

        old_flags = flags_for_items(old_doc.line_items)
        new_flags = flags_for_items(new_items)

        old_count = len(old_doc.line_items)
        new_count = len(new_items)

        if not new_flags and (old_flags or old_count != new_count):
            fixed += 1
            status = "FIXED on re-parse"
        elif new_flags:
            still_bad += 1
            status = "STILL HAS ISSUES"
        else:
            status = "OK (false positive)"

        print(f"  {file_name}")
        print(f"    items: {old_count} -> {new_count} | {status}")
        if old_flags:
            print(f"    stored:  {'; '.join(old_flags[:2])}")
        if new_flags:
            print(f"    fresh:   {'; '.join(new_flags[:2])}")

    print(f"\nSummary: fixed={fixed}, still_bad={still_bad}, missing_pdf={missing_pdf}")


if __name__ == "__main__":
    main()
