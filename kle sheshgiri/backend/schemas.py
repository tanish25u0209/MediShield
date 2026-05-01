from typing import Any, Literal

from pydantic import BaseModel, Field


class ParsedFields(BaseModel):
    medicine_name: str | None = None
    batch_number: str | None = None
    mfg_date: str | None = None
    exp_date: str | None = None
    manufacturer: str | None = None


class Issue(BaseModel):
    code: str
    message: str
    severity: Literal["low", "medium", "high"]


class RiskPreviewRequest(BaseModel):
    medicine_name: str | None = None
    batch_number: str | None = None
    mfg_date: str | None = None
    exp_date: str | None = None
    manufacturer: str | None = None
    ocr_confidence: float | None = None


class ImageDiagnostics(BaseModel):
    image_index: int
    blur_score: float
    brightness: float
    contrast: float
    is_blurry: bool
    is_low_quality: bool
    is_distorted: bool


class DrugInfo(BaseModel):
    name: str
    generic_name: str | None = None
    dosage: str | None = None
    manufacturer: str | None = None
    therapeutic_class: str | None = None
    uses: list[str] = Field(default_factory=list)
    conditions_treated: list[str] = Field(default_factory=list)
    assistant_summary: str | None = None
    reference_sources: list[str] = Field(default_factory=list)
    side_effects: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    notes: str | None = None
    is_true_medicine: bool = False
    true_medicine_source: str | None = None
    is_fake_medicine: bool = False
    fake_medicine_source: str | None = None
    is_banned: bool = False
    ban_source: str | None = None


class ScanResponse(BaseModel):
    request_id: str
    status: Literal["Safe", "Suspicious", "High Risk"]
    risk_score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=100)
    parsed_data: ParsedFields
    display_fields: dict[str, Any] | None = None
    reasons: list[Issue]
    diagnostics: list[ImageDiagnostics]
    drug_info: DrugInfo | None = None
    ml_insights: dict[str, Any] | None = None
    pipeline_output: dict[str, Any] | None = None
    pipeline_error: str | None = None
