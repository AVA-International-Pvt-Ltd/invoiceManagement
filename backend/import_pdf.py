"""Import one or more PDFs into the database (same as Upload page).

Usage:
    python import_pdf.py "C:\\path\\to\\file.pdf"
    python import_pdf.py "C:\\folder\\with\\pdfs"
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path
from uuid import uuid4

from app.models import JobResult
from app.pipeline import DocumentPipeline
from app.storage import UPLOAD_DIR, build_extraction_payload, ensure_dirs, save_extraction


def import_pdf(pdf: Path, pipeline: DocumentPipeline) -> tuple[str, int]:
    ensure_dirs()
    dest = UPLOAD_DIR / pdf.name
    if dest.resolve() != pdf.resolve():
        shutil.copy2(pdf, dest)

    job_id = str(uuid4())
    doc = pipeline.run(source_uri=str(dest), file_name=dest.name, file_path=dest)
    job = JobResult(job_id=job_id, status="completed", document=doc)
    save_extraction(job_id, build_extraction_payload(job_id, job.model_dump(mode="json")))
    return job_id, len(doc.line_items)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python import_pdf.py <pdf-file-or-folder>")
        raise SystemExit(1)

    target = Path(sys.argv[1])
    if not target.exists():
        print(f"Not found: {target}")
        raise SystemExit(1)

    pdfs = sorted(target.glob("*.pdf")) if target.is_dir() else [target]
    if not pdfs:
        print("No PDF files found.")
        raise SystemExit(1)

    pipeline = DocumentPipeline()
    print(f"Importing {len(pdfs)} PDF(s)...\n")
    for pdf in pdfs:
        job_id, items = import_pdf(pdf, pipeline)
        print(f"  OK  {pdf.name}  ->  {job_id}  ({items} line items)")

    print(f"\nDone. Imported {len(pdfs)} document(s). Restart backend if it is already running.")


if __name__ == "__main__":
    main()
