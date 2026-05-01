"""
Structured Output Schemas for MediShield Pipeline

Defines standardized dataclass schemas for all pipeline components.
Ensures consistent, type-safe data flow across engines.
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
from enum import Enum
import json


@dataclass
class FinalField:
    """Final validated field output for truth verifier."""
    value: Optional[str]
    state: str  # CONFIRMED | REJECTED
    confidence_score: float
    rejection_reason: str = ""
    failure_mode: str = ""
    evidence_sources: List[Any] = field(default_factory=list)
    signal_breakdown: Dict[str, Any] = field(default_factory=dict)
    validation_flags: Dict[str, bool] = field(default_factory=lambda: {
        "evidence_sufficient": False,
        "no_contradiction": False,
        "cross_image_supported": False,
        "noise_within_limit": False,
    })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "state": self.state,
            "confidence_score": round(float(self.confidence_score or 0.0), 4),
            "rejection_reason": self.rejection_reason,
            "failure_mode": self.failure_mode,
            "evidence_sources": list(self.evidence_sources),
            "signal_breakdown": dict(self.signal_breakdown),
            "validation_flags": dict(self.validation_flags),
        }


class RiskLevel(Enum):
    """Risk classification levels"""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ConfidenceLevel(Enum):
    """Confidence in predictions"""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class PackagingForm(Enum):
    """Valid packaging forms"""
    TABLET = "TABLET"
    CAPSULE = "CAPSULE"
    SYRUP = "SYRUP"
    INJECTION = "INJECTION"
    CREAM = "CREAM"
    POWDER = "POWDER"
    UNKNOWN = "UNKNOWN"


# ============================================================================
# OCR ENGINE SCHEMAS
# ============================================================================

@dataclass
class OCRFieldDetection:
    """Per-field OCR detection result."""
    value: Optional[str]
    confidence: float  # 0.0-1.0 per-field confidence
    raw_value: Optional[str]  # Before normalization
    region: Optional[str] = None  # top/middle/bottom/full if applicable
    regex_match: bool = False  # Whether regex pattern matched


@dataclass
class OCRImageResult:
    """OCR result from processing a single image."""
    image_path: str
    medicine_name: OCRFieldDetection
    batch_number: OCRFieldDetection
    expiry_date: OCRFieldDetection
    mfg_date: OCRFieldDetection
    manufacturer: OCRFieldDetection
    raw_text: str  # Full OCR text before extraction
    preprocessing_log: Dict[str, Any] = field(default_factory=dict)  # Preprocessing steps applied
    overall_confidence: float = 0.0  # Aggregate OCR text confidence


@dataclass
class OCREngineOutput:
    """Complete OCR engine output."""
    image_results: List[OCRImageResult]
    raw_combined_text: str  # Combined raw OCR from all images
    processing_time_seconds: float
    notes: List[str] = field(default_factory=list)

    def to_dict(self):
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


# ============================================================================
# FUSION ENGINE SCHEMAS
# ============================================================================

@dataclass
class FieldFusion:
    """Per-field fusion result with agreement metrics."""
    final_value: Optional[str]
    confidence: float  # 0.0-1.0 from weighted agreement
    agreement_score: float  # Fraction of images agreeing
    weighted_score: float  # Sum of weights that agreed
    conflicting_values: Dict[str, float] = field(default_factory=dict)  # Other values found with weights
    is_confident: bool = True  # True if agreement_score >= 0.6 or single image


@dataclass
class FusionConflict:
    """Recorded conflict in field fusion."""
    field_name: str
    conflicting_values: List[str]
    confidence_per_variant: Dict[str, float]
    resolution: str  # Which value was selected and why


@dataclass
class FusionEngineOutput:
    """Complete fusion engine output."""
    medicine_name: FieldFusion
    batch_number: FieldFusion
    expiry_date: FieldFusion
    mfg_date: FieldFusion
    manufacturer: FieldFusion
    overall_field_confidence: float  # Average across all fields
    conflicts_detected: List[FusionConflict]
    consistency_score: float  # How well images agree on critical fields
    fusion_method: str = "weighted_majority_vote"
    processing_time_seconds: float = 0.0

    def to_dict(self):
        """Convert to dictionary."""
        return asdict(self)


# ============================================================================
# VALIDATION ENGINE SCHEMAS
# ============================================================================

@dataclass
class ValidationIssue:
    """Single validation issue found."""
    field: str
    severity: str  # "ERROR" or "WARNING"
    message: str
    rule_violated: str


@dataclass
class ValidationEngineOutput:
    """Complete validation engine output."""
    is_valid: bool  # True if no critical errors
    issues: List[ValidationIssue] = field(default_factory=list)
    completeness_score: float = 1.0  # Fraction of required fields present (0.0-1.0)
    data_quality_score: float = 1.0  # Overall data quality metric
    processing_time_seconds: float = 0.0

    def to_dict(self):
        """Convert to dictionary."""
        return asdict(self)


# ============================================================================
# CLASSIFIER ENGINE SCHEMAS
# ============================================================================

@dataclass
class ClassifierPerImageResult:
    """Classification result for single image."""
    image_path: str
    predicted_form: PackagingForm
    confidence: float


@dataclass
class ClassifierEngineOutput:
    """Complete classifier engine output."""
    final_form: PackagingForm
    confidence: float  # 0.0-1.0 overall confidence
    per_image_results: List[ClassifierPerImageResult]
    consensus_method: str = "majority_vote"
    processing_time_seconds: float = 0.0

    def to_dict(self):
        """Convert to dictionary."""
        data = asdict(self)
        data['final_form'] = data['final_form'].value
        return data


# ============================================================================
# RISK ENGINE SCHEMAS
# ============================================================================

@dataclass
class RiskSignal:
    """Individual risk signal component."""
    name: str  # e.g., "consistency", "ocr_reliability", "validation_score"
    raw_value: float  # 0.0-1.0 raw signal
    weighted_value: float  # After applying weight
    weight: float  # Component weight in overall score
    explanation: str


@dataclass
class RiskExplanationItem:
    """Single item in risk explanation."""
    reason: str
    penalty_or_boost: int  # How many points this contributes
    severity: str  # "CRITICAL", "MAJOR", "MINOR"


@dataclass
class RiskEngineOutput:
    """Complete risk engine output."""
    risk_score: int  # 0-100
    risk_level: RiskLevel
    confidence_level: ConfidenceLevel
    explanation: List[RiskExplanationItem]
    signal_components: List[RiskSignal]
    thresholds_used: Dict[str, int] = field(default_factory=dict)
    processing_time_seconds: float = 0.0

    def to_dict(self):
        """Convert to dictionary."""
        data = asdict(self)
        data['risk_level'] = data['risk_level'].value
        data['confidence_level'] = data['confidence_level'].value
        return data


# ============================================================================
# PIPELINE ORCHESTRATOR SCHEMAS
# ============================================================================

@dataclass
class PipelineExecutionTrace:
    """Complete execution trace for debugging and logging."""
    stage: str  # "ocr", "fusion", "validation", "classifier", "risk"
    timestamp: str  # ISO format
    input_summary: Dict[str, Any]
    output_summary: Dict[str, Any]
    processing_time_seconds: float
    errors: List[str] = field(default_factory=list)


@dataclass
class MediShieldPipelineOutput:
    """
    Complete MediShield pipeline output.
    
    This is the unified output schema returned by pipeline_orchestrator.
    All components follow consistent, structured output.
    """
    # Core predictions
    ocr_result: OCREngineOutput
    fusion_result: FusionEngineOutput
    validation_result: ValidationEngineOutput
    classification_result: ClassifierEngineOutput
    risk_result: RiskEngineOutput

    # Consolidated final outputs
    # final_data now stores per-field validated outputs using FinalField
    final_data: Dict[str, Any]  # mapping field -> FinalField (see FinalField dataclass)
    final_form: PackagingForm
    final_risk_score: int
    final_risk_level: RiskLevel

    # Traceability
    execution_trace: List[PipelineExecutionTrace]
    images_processed: int
    total_processing_time_seconds: float

    # Backward compatibility layer
    backward_compatibility_data: Dict[str, Any] = field(default_factory=dict)  # For existing eval harness

    def to_dict(self):
        """Convert to dictionary for JSON serialization."""
        data = {
            "ocr": self.ocr_result.to_dict(),
            "fusion": self.fusion_result.to_dict(),
            "validation": self.validation_result.to_dict(),
            "classification": self.classification_result.to_dict(),
            "risk": self.risk_result.to_dict(),
            # final_data may contain dataclasses; convert to plain dicts where needed
            "final_data": {
                k: (v.to_dict() if hasattr(v, "to_dict") else v) for k, v in self.final_data.items()
            },
            "final_form": self.final_form.value,
            "final_risk_score": self.final_risk_score,
            "final_risk_level": self.final_risk_level.value,
            "images_processed": self.images_processed,
            "total_processing_time_seconds": self.total_processing_time_seconds,
            "execution_trace": [asdict(trace) for trace in self.execution_trace],
        }
        return data

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2, default=str)


# ============================================================================
# LEGACY COMPATIBILITY HELPER
# ============================================================================

def convert_to_legacy_format(pipeline_output: MediShieldPipelineOutput) -> Dict[str, Any]:
    """
    Convert new structured output to legacy format for backward compatibility.
    
    This allows evaluation harness to continue working without modification.
    """
    # Ensure final_data is backward-compatible: map FinalField -> its value
    def _unwrap_final(v):
        try:
            # FinalField dataclass exposes `value`
            return v.value if hasattr(v, "value") else v
        except Exception:
            return v

    legacy_final_data = {k: _unwrap_final(v) for k, v in pipeline_output.final_data.items()}

    return {
        "final_data": legacy_final_data,
        "per_image_data": [
            {
                "fields": {
                    "medicine_name": result.medicine_name.value,
                    "batch_number": result.batch_number.value,
                    "expiry_date": result.expiry_date.value,
                    "mfg_date": result.mfg_date.value,
                    "manufacturer": result.manufacturer.value,
                },
                "confidence": result.overall_confidence,
                "raw_text": result.raw_text,
            }
            for result in pipeline_output.ocr_result.image_results
        ],
        "derived_parameters": {
            "consistency_score": pipeline_output.fusion_result.consistency_score,
            "agreement_score": pipeline_output.fusion_result.overall_field_confidence,
            "ocr_confidence": sum(
                r.overall_confidence for r in pipeline_output.ocr_result.image_results
            ) / len(pipeline_output.ocr_result.image_results) if pipeline_output.ocr_result.image_results else 0.0,
        },
        "validation": {
            "is_valid": pipeline_output.validation_result.is_valid,
            "completeness_score": pipeline_output.validation_result.completeness_score,
        },
        "conflicts": [
            f"{c.field_name}: {c.conflicting_values}"
            for c in pipeline_output.fusion_result.conflicts_detected
        ],
        "risk_score": pipeline_output.final_risk_score,
        "risk_level": pipeline_output.final_risk_level.value,
    }
