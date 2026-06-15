"""One-shot: re-run the pipeline on every previously-extracted document
and overwrite its JSON with fresh, fixed output.

- Preserves existing job IDs (so any links/bookmarks keep working).
- Reads each `data/extractions/{job_id}.json` to find the original PDF path.
- Falls back to `data/uploads/{file_name}` if the recorded path is missing.
- Updates `data/index.json` automatically through `save_extraction()`.

Usage:  python reprocess_all.py
"""
from __future__ import annotations

import json
from pathlib import Path

from app.models import JobResult
from app.pipeline import DocumentPipeline
from app.storage import (
    EXTRACTIONS_DIR,
    UPLOAD_DIR,
    build_extraction_payload,
    save_extraction,
)


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


def main() -> None:
    pipeline = DocumentPipeline()
    json_files = sorted(EXTRACTIONS_DIR.glob("*.json"))
    if not json_files:
        print("No extractions found.")
        return

    print(f"Re-processing {len(json_files)} document(s)...\n")
    print(f"{'#':>3} {'job_id':<38} {'file':<28} {'items':>5} {'qty':>5} {'total':>11}  status")
    print("-" * 110)

    skipped: list[tuple[str, str]] = []
    for idx, path in enumerate(json_files, 1):
        job_id = path.stem
        try:
            stored = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            skipped.append((job_id, f"unreadable JSON: {exc}"))
            continue

        pdf = find_pdf(stored)
        if pdf is None:
            file_name = (stored.get("document") or {}).get("audit", {}).get("file_name", "?")
            skipped.append((job_id, f"source PDF missing for {file_name!r}"))
            continue

        try:
            doc = pipeline.run(source_uri=str(pdf), file_name=pdf.name, file_path=pdf)
            job = JobResult(job_id=job_id, status="completed", document=doc)
            payload = build_extraction_payload(job_id, job.model_dump(mode="json"))
            save_extraction(job_id, payload)

            qty_sum = sum(i.quantity for i in doc.line_items)
            total_sum = round(sum(i.total_amount for i in doc.line_items), 2)
            print(
                f"{idx:>3} {job_id:<38} {pdf.name:<28} "
                f"{len(doc.line_items):>5} {qty_sum:>5.0f} {total_sum:>11.2f}  OK"
            )
        except Exception as exc:
            skipped.append((job_id, f"pipeline error: {exc}"))
            print(f"{idx:>3} {job_id:<38} {pdf.name:<28} {'-':>5} {'-':>5} {'-':>11}  FAIL")

    print("-" * 110)
    print(f"Re-processed: {len(json_files) - len(skipped)} / {len(json_files)}")
    if skipped:
        print(f"\nSkipped {len(skipped)}:")
        for job_id, reason in skipped:
            print(f"  - {job_id}: {reason}")


if __name__ == "__main__":
    main()
