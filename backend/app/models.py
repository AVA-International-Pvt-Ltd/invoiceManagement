from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    invoice = "invoice"
    credit_note = "credit_note"
    debit_note = "debit_note"
    r4c = "r4c"
    settlement = "settlement"
    purchase_order = "purchase_order"
    unknown = "unknown"


class Party(BaseModel):
    name: str = ""
    gstin: str = ""
    pan: str = ""
    address: str = ""


class SourceRef(BaseModel):
    page: int | None = None
    bbox: list[float] = Field(default_factory=list)
    confidence: float | None = None


class LineItem(BaseModel):
    system_ref_no: str = ""
    invoice_date: str = ""
    invoice_no: str = ""
    combo: str = ""
    document_date: str = ""
    document_number: str = ""
    asin: str = ""
    sku: str = ""
    ean: str = ""
    hsn: str = ""
    product: str = ""
    tally_name: str = ""
    units: str = ""
    ship_to_state: str = ""
    warehouse: str = ""
    tax_type: str = ""
    tax_rate: float = 0.0
    quantity: float = 0.0
    cost_per_unit: float = 0.0
    total_cost: float = 0.0
    tax_amount: float = 0.0
    total_amount: float = 0.0
    return_id: str = ""
    shipment_id: str = ""
    source_ref: SourceRef | None = None


class RawPage(BaseModel):
    page_number: int
    raw_text: str = ""
    ocr_tokens: list[dict[str, Any]] = Field(default_factory=list)
    tables: list[dict[str, Any]] = Field(default_factory=list)
    images: list[dict[str, Any]] = Field(default_factory=list)
    coordinates: list[dict[str, Any]] = Field(default_factory=list)


class ValidationResult(BaseModel):
    status: str = "warning"
    confidence: float = 0.0
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class NormalizedDocument(BaseModel):
    document_id: str
    document_type: DocumentType = DocumentType.unknown
    confidence: float = 0.0
    header: dict[str, Any] = Field(default_factory=dict)
    vendor: Party = Field(default_factory=Party)
    customer: Party = Field(default_factory=Party)
    billing_address: dict[str, Any] = Field(default_factory=dict)
    shipping_address: dict[str, Any] = Field(default_factory=dict)
    receiver_billing_address: dict[str, Any] = Field(default_factory=dict)
    receiver_shipping_address: dict[str, Any] = Field(default_factory=dict)
    line_items: list[LineItem] = Field(default_factory=list)
    tax_summary: dict[str, Any] = Field(default_factory=dict)
    totals: dict[str, Any] = Field(default_factory=dict)
    validation: ValidationResult = Field(default_factory=ValidationResult)
    raw_data: dict[str, Any] = Field(default_factory=lambda: {"pages": []})
    audit: dict[str, Any] = Field(default_factory=dict)


class ProcessRequest(BaseModel):
    source_uri: str
    file_name: str
    tenant_id: str = "default"


class ProcessResponse(BaseModel):
    job_id: str
    status: str
    is_duplicate: bool = False
    duplicate_upload_number: int = 1
    duplicate_of_job_id: str | None = None
    duplicate_message: str | None = None
    extraction_status: str | None = None
    extraction_status_label: str | None = None
    extraction_status_symbol: str | None = None
    extraction_issues: list[str] = Field(default_factory=list)
    data_quality: str | None = None
    profile_matched: bool = True
    profile_alerts: list[str] = Field(default_factory=list)


class JobResult(BaseModel):
    job_id: str
    status: str
    document: NormalizedDocument | None = None


class ExportSelectedRequest(BaseModel):
    job_ids: list[str]
