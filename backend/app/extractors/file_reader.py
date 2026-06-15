from __future__ import annotations

from pathlib import Path
from typing import Any

from ..models import RawPage


def read_document(file_path: Path) -> list[RawPage]:
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return _read_pdf(file_path)
    if suffix in {".jpg", ".jpeg", ".png", ".tif", ".tiff"}:
        return _read_image(file_path)
    raise ValueError(f"Unsupported file type: {suffix}")


def _read_pdf(file_path: Path) -> list[RawPage]:
    import pdfplumber

    pages: list[RawPage] = []
    with pdfplumber.open(file_path) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            raw_text = page.extract_text() or ""
            tables = []
            for table in page.extract_tables() or []:
                cleaned = [[_clean_cell(cell) for cell in row] for row in table if row]
                if cleaned:
                    tables.append({"rows": cleaned, "source": "pdfplumber"})

            words = page.extract_words() or []
            coordinates = [
                {
                    "text": w.get("text", ""),
                    "x0": float(w.get("x0", 0.0)),
                    "x1": float(w.get("x1", 0.0)),
                    "top": float(w.get("top", 0.0)),
                    "bottom": float(w.get("bottom", 0.0)),
                }
                for w in words
            ]

            pages.append(
                RawPage(
                    page_number=index,
                    raw_text=raw_text,
                    ocr_tokens=_text_to_tokens(raw_text),
                    tables=tables,
                    images=[],
                    coordinates=coordinates,
                )
            )
    return pages


def _read_image(file_path: Path) -> list[RawPage]:
    raw_text = ""
    warning = ""
    try:
        import pytesseract
        from PIL import Image

        image = Image.open(file_path)
        raw_text = pytesseract.image_to_string(image)
    except Exception as exc:
        warning = f"OCR unavailable: {exc}"

    if not raw_text.strip():
        raw_text = warning or "No text extracted from image."

    return [
        RawPage(
            page_number=1,
            raw_text=raw_text,
            ocr_tokens=_text_to_tokens(raw_text),
            tables=[],
            images=[{"path": str(file_path), "type": "source_image"}],
            coordinates=[],
        )
    ]


def _clean_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _text_to_tokens(text: str) -> list[dict[str, Any]]:
    tokens: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines()):
        for word_no, word in enumerate(line.split()):
            if word:
                tokens.append(
                    {
                        "text": word,
                        "line": line_no,
                        "index": word_no,
                        "confidence": 1.0,
                    }
                )
    return tokens
