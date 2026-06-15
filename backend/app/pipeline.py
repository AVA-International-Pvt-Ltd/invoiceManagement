from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from .extractors import parse_document, read_document
from .models import DocumentType, LineItem, NormalizedDocument, Party, ValidationResult


@dataclass
class ProcessingContext:
    document_id: str
    source_uri: str
    file_name: str
    file_path: Path | None = None
    classification: dict[str, Any] = field(default_factory=dict)
    raw_pages: list = field(default_factory=list)
    extracted_fields: dict[str, Any] = field(default_factory=dict)
    line_items: list[LineItem] = field(default_factory=list)
    validations: ValidationResult = field(default_factory=ValidationResult)
    metadata: dict[str, Any] = field(default_factory=dict)


class DocumentPipeline:
    def run(self, source_uri: str, file_name: str, file_path: Path | None = None) -> NormalizedDocument:
        ctx = ProcessingContext(
            document_id=str(uuid4()),
            source_uri=source_uri,
            file_name=file_name,
            file_path=file_path,
        )
        self.classify(ctx)
        self.ocr_and_layout(ctx)
        self.extract_entities(ctx)
        self.extract_line_items(ctx)
        self.validate(ctx)
        return self.normalize(ctx)

    def classify(self, ctx: ProcessingContext) -> None:
        if ctx.extracted_fields.get("document_type"):
            return
        lower_name = ctx.file_name.lower()
        guess = DocumentType.unknown
        if "credit" in lower_name:
            guess = DocumentType.credit_note
        elif "debit" in lower_name:
            guess = DocumentType.debit_note
        elif "invoice" in lower_name:
            guess = DocumentType.invoice
        elif "r4c" in lower_name:
            guess = DocumentType.r4c
        ctx.classification = {"document_type": guess.value, "confidence": 0.5}

    def ocr_and_layout(self, ctx: ProcessingContext) -> None:
        if ctx.file_path and ctx.file_path.exists():
            ctx.raw_pages = read_document(ctx.file_path)
            ctx.metadata["pages_processed"] = len(ctx.raw_pages)
            return

        from .models import RawPage

        ctx.raw_pages = [
            RawPage(
                page_number=1,
                raw_text=f"No file content available for {ctx.file_name}",
                ocr_tokens=[],
                tables=[],
                images=[],
                coordinates=[],
            )
        ]

    def extract_entities(self, ctx: ProcessingContext) -> None:
        if not ctx.raw_pages:
            return

        parsed = parse_document(ctx.file_name, ctx.raw_pages)
        ctx.classification = {
            "document_type": parsed["document_type"].value,
            "confidence": parsed["classification_confidence"],
        }
        ctx.extracted_fields = {
            "document_type": parsed["document_type"],
            "header": parsed["header"],
            "vendor": parsed["vendor"].model_dump(),
            "customer": parsed["customer"].model_dump(),
            "billing_address": parsed["billing_address"],
            "shipping_address": parsed["shipping_address"],
            "receiver_billing_address": parsed["receiver_billing_address"],
            "receiver_shipping_address": parsed["receiver_shipping_address"],
            "tax_summary": parsed["tax_summary"],
            "totals": parsed["totals"],
        }
        ctx.line_items = parsed["line_items"]

    def extract_line_items(self, ctx: ProcessingContext) -> None:
        return

    def validate(self, ctx: ProcessingContext) -> None:
        errors: list[str] = []
        warnings: list[str] = []

        header = ctx.extracted_fields.get("header", {})
        totals = ctx.extracted_fields.get("totals", {})
        tax_summary = ctx.extracted_fields.get("tax_summary", {})

        doc_no = (
            header.get("debit_note_number")
            or header.get("invoice_number")
            or header.get("document_number")
        )
        if not doc_no:
            warnings.append("Missing invoice/document number")

        vendor = ctx.extracted_fields.get("vendor", {})
        if not vendor.get("gstin"):
            warnings.append("Missing vendor GSTIN")

        line_tax = round(sum(item.tax_amount for item in ctx.line_items), 2)
        invoice_tax = round(float(totals.get("tax_total", 0.0) or sum(tax_summary.values())), 2)
        if ctx.line_items and invoice_tax and abs(line_tax - invoice_tax) > 1.0:
            warnings.append(f"Tax mismatch: line items {line_tax} vs invoice {invoice_tax}")

        line_total = round(sum(item.total_amount for item in ctx.line_items), 2)
        grand_total = round(float(totals.get("grand_total", 0.0)), 2)
        if ctx.line_items and grand_total and abs(line_total - grand_total) > 1.0:
            warnings.append(f"Total mismatch: line items {line_total} vs invoice {grand_total}")

        if not ctx.raw_pages or not any(page.raw_text.strip() for page in ctx.raw_pages):
            errors.append("No extractable text found in document")

        ctx.validations = ValidationResult(
            status="invalid" if errors else ("warning" if warnings else "valid"),
            confidence=95.0 if not errors and not warnings else 78.0 if not errors else 55.0,
            errors=errors,
            warnings=warnings,
        )

    def normalize(self, ctx: ProcessingContext) -> NormalizedDocument:
        doc_type = DocumentType(ctx.classification.get("document_type", DocumentType.unknown.value))
        confidence = float(ctx.classification.get("confidence", 0.0)) * 100

        return NormalizedDocument(
            document_id=ctx.document_id,
            document_type=doc_type,
            confidence=round(confidence, 2),
            header=ctx.extracted_fields.get("header", {}),
            vendor=Party(**ctx.extracted_fields.get("vendor", {})),
            customer=Party(**ctx.extracted_fields.get("customer", {})),
            billing_address=ctx.extracted_fields.get("billing_address", {}),
            shipping_address=ctx.extracted_fields.get("shipping_address", {}),
            receiver_billing_address=ctx.extracted_fields.get("receiver_billing_address", {}),
            receiver_shipping_address=ctx.extracted_fields.get("receiver_shipping_address", {}),
            line_items=ctx.line_items,
            tax_summary=ctx.extracted_fields.get("tax_summary", {}),
            totals=ctx.extracted_fields.get("totals", {}),
            validation=ctx.validations,
            raw_data={"pages": [p.model_dump() for p in ctx.raw_pages]},
            audit={
                "source_uri": ctx.source_uri,
                "file_name": ctx.file_name,
                "pipeline_version": "v1",
                "pages_processed": ctx.metadata.get("pages_processed", len(ctx.raw_pages)),
            },
        )
