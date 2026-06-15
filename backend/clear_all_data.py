"""Delete every stored document (uploads + extractions + index).

Usage:  python clear_all_data.py
"""
from __future__ import annotations

import json

from app.storage import EXTRACTIONS_DIR, INDEX_FILE, UPLOAD_DIR, ensure_dirs


def main() -> None:
    ensure_dirs()
    removed_json = 0
    removed_pdf = 0

    for path in EXTRACTIONS_DIR.glob("*.json"):
        path.unlink()
        removed_json += 1

    for path in UPLOAD_DIR.iterdir():
        if path.is_file():
            path.unlink()
            removed_pdf += 1

    INDEX_FILE.write_text(
        json.dumps({"jobs": [], "count": 0}, indent=2),
        encoding="utf-8",
    )

    print(f"Cleared {removed_json} extraction(s) and {removed_pdf} upload(s).")
    print("Index reset to empty. Restart the backend, then upload or run import_pdf.py.")


if __name__ == "__main__":
    main()
