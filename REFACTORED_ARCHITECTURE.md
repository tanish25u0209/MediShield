# MediShield Refactored Pipeline Architecture

## Overview

This document describes the refactored MediShield backend—a clean, modular, production-grade ML pipeline for pharmaceutical counterfeit detection.

**Status:** ✅ Complete refactoring with full backward compatibility

---

## Architecture Principles

### 1. **Modularity**
Each component is independently testable and deployable:
- **OCREngine** — Text extraction with confidence scoring
- **FusionEngine** — Multi-image consensus and conflict resolution
- **ValidationEngine** — Data quality checks and completeness scoring
- **ClassifierEngine** — Packaging form classification
- **RiskEngineV2** — Comprehensive risk assessment

### 2. **Structured Output**
All components return strict dataclass schemas (defined in `pipeline_schemas.py`):
```python
@dataclass
class OCREngineOutput:
    image_results: List[OCRImageResult]
    raw_combined_text: str
    processing_time_seconds: float

@dataclass
class FusionEngineOutput:
    medicine_name: FieldFusion
    batch_number: FieldFusion
    ...
    consistency_score: float
```

### 3. **Transparency & Traceability**
Every step is logged with inputs, outputs, and timing:
```python
execution_trace: List[PipelineExecutionTrace]
# Example: [
#   {stage: "ocr", timestamp: "...", input: {...}, output: {...}, time_ms: 234},
#   {stage: "fusion", ...},
#   ...
# ]
```

### 4. **Backward Compatibility**
Existing evaluation code works transparently via adapter:
```python
# Old code (still works):
from medishield_pipeline_refactored import process_medicine
result = process_medicine(["img1.jpg"])

# New code (structured):
from medishield_pipeline_refactored import MediShieldPipelineAdapter
adapter = MediShieldPipelineAdapter()
structured_result = adapter.process_medicine_images_new(["img1.jpg"])
```

---

## Pipeline Stages

### Stage 1: OCREngine (`ocr_engine.py`)

**Purpose:** Extract medicine metadata from packaging images

**Improvements over original:**
- **Adaptive Preprocessing** — Analyzes brightness/contrast and applies CLAHE
- **Per-Field Confidence** — Each field gets independent confidence score
- **Region Fallback** — If field confidence is low, tries region-specific extraction
- **Multi-PSM Extraction** — Tries 3 Tesseract PSM modes, selects best

**Output:**
```python
OCREngineOutput(
    image_results: [
        OCRImageResult(
            medicine_name: OCRFieldDetection(value="Paracetamol", confidence=0.85, ...),
            batch_number: OCRFieldDetection(value="00145", confidence=0.92, ...),
            expiry_date: OCRFieldDetection(value="06/2024", confidence=0.88, ...),
            mfg_date: OCRFieldDetection(value="12/2023", confidence=0.80, ...),
            manufacturer: OCRFieldDetection(value="ABC Pharma", confidence=0.75, ...),
            overall_confidence: 0.84,
            preprocessing_log: {resize: "...", clahe: "...", ...}
        ),
        ...
    ],
    processing_time_seconds: 1.23
)
```

**Key Methods:**
- `_adaptive_preprocess()` — Size normalization, CLAHE, denoising, thresholding
- `_extract_text_multimodal()` — Try multiple PSM configs, pick best confidence
- `_extract_fields_with_confidence()` — Regex + per-field confidence scoring
- `_apply_region_fallback()` — Low-confidence fallback to region extraction

---

### Stage 2: FusionEngine (`fusion_engine.py`)

**Purpose:** Combine results from multiple images with weighted consensus

**Improvements over original:**
- **Weighted Agreement** — Each value voted with OCR confidence weight
- **Conflict Tracking** — Records discrepancies between images
- **Consistency Scoring** — How well do images agree on critical fields?
- **Mathematical Transparency** — Full breakdown of voting

**Algorithm:**
```
For each field:
  1. Collect all (value, confidence) pairs from all images
  2. Tally: vote_tally[value] += confidence
  3. Normalize: vote_tally[value] / total_confidence
  4. Winner = highest weighted value
  5. Compute agreement_score = fraction of images voting for winner
  6. Compute fusion_confidence = 0.6 * agreement + 0.4 * winning_vote
```

**Output:**
```python
FusionEngineOutput(
    batch_number: FieldFusion(
        final_value="00145",
        confidence=0.92,
        agreement_score=1.0,  # All 2 images agreed
        weighted_score=0.92,
        conflicting_values={},
        is_confident=True
    ),
    ...
    consistency_score=0.95,  # Critical fields all agreed
    conflicts_detected=[],
    processing_time_seconds=0.05
)
```

**Key Methods:**
- `_collect_field_results()` — Extract per-image results
- `_fuse_field()` — Weighted voting per field
- `_compute_consistency_score()` — Agreement on critical fields

---

### Stage 3: ValidationEngine (`validation_engine.py`)

**Purpose:** Check data quality and compliance with business rules

**Validations:**
- ✅ Required fields present (batch_number, expiry_date)
- ✅ Date format valid (MM/YYYY)
- ✅ Product not expired
- ✅ Manufacturing date < expiry date
- ✅ Batch number format reasonable
- ✅ Medicine name length > 2 characters

**Severity Levels:**
- ERROR: Critical issue (missing batch, expired, invalid format)
- WARNING: Important issue (missing mfg_date, unusual batch format)

**Output:**
```python
ValidationEngineOutput(
    is_valid=True,  # No ERRORs
    issues=[
        ValidationIssue(
            field="mfg_date",
            severity="WARNING",
            message="Missing manufacturing date",
            rule_violated="IMPORTANT_FIELD_MISSING"
        )
    ],
    completeness_score=0.8,  # 4/5 fields present
    data_quality_score=0.85,  # After penalties
    processing_time_seconds=0.02
)
```

**Key Methods:**
- `_is_valid_date_format()` — MM/YYYY validation
- `_is_expired()` — Check expiry against today
- `_validate_date_order()` — Mfg before expiry
- `_compute_completeness()` — Field presence ratio
- `_compute_data_quality()` — Quality score with deductions

---

### Stage 4: ClassifierEngine (`classifier_engine.py`)

**Purpose:** Detect packaging form (tablet, capsule, syrup, etc.)

**Improvements:**
- **Consensus** — Combines predictions from multiple images
- **Confidence Weighting** — Fuses per-image confidences

**Forms:**
- TABLET, CAPSULE, SYRUP, INJECTION, CREAM, POWDER, UNKNOWN

**Output:**
```python
ClassifierEngineOutput(
    final_form=PackagingForm.TABLET,
    confidence=0.92,
    per_image_results=[
        ClassifierPerImageResult(
            image_path="img1.jpg",
            predicted_form=PackagingForm.TABLET,
            confidence=0.93
        ),
        ...
    ],
    consensus_method="majority_vote",
    processing_time_seconds=0.15
)
```

---

### Stage 5: RiskEngineV2 (`risk_engine_v2.py`)

**Purpose:** Comprehensive authenticity risk assessment with explanations

**Scoring Model:**
```
Risk Score = 1.0 - Weighted(
    consistency: 0.30,      # Multi-image agreement
    validation: 0.25,       # Data validation results
    ocr_reliability: 0.20,  # OCR confidence
    classifier_anomaly: 0.15,  # Packaging form
    field_completeness: 0.10   # Field presence
)
```

**Risk Levels:**
- LOW: 0-34 points → Safe product
- MEDIUM: 35-64 points → Suspicious (manual review)
- HIGH: 65-100 points → High risk

**Confidence Levels:** LOW, MEDIUM, HIGH
- Based on image count, consistency, and number of issues

**Output:**
```python
RiskEngineOutput(
    risk_score=28,
    risk_level=RiskLevel.LOW,
    confidence_level=ConfidenceLevel.HIGH,
    explanation=[
        RiskExplanationItem(
            reason="All fields extracted confidently",
            penalty_or_boost=0,
            severity="MINOR"
        ),
        RiskExplanationItem(
            reason="High multi-image agreement (100%)",
            penalty_or_boost=+10,
            severity="MINOR"
        ),
    ],
    signal_components=[  # Full breakdown per signal
        RiskSignal(
            name="consistency",
            raw_value=0.95,
            weighted_value=0.95,
            weight=0.30,
            explanation="..."
        ),
        ...
    ],
    thresholds_used={
        "low_upper": 34,
        "medium_upper": 64,
        "high_lower": 65
    }
)
```

**Key Methods:**
- `_compute_*_signal()` — Per-component signal calculation
- `_compute_weighted_score()` — Weighted aggregation
- `_map_risk_level()` — Threshold mapping
- `_generate_explanations()` — Issue detection

---

## Final Output: MediShieldPipelineOutput

**Complete, type-safe output from entire pipeline:**

```python
@dataclass
class MediShieldPipelineOutput:
    # All stage results
    ocr_result: OCREngineOutput
    fusion_result: FusionEngineOutput
    validation_result: ValidationEngineOutput
    classification_result: ClassifierEngineOutput
    risk_result: RiskEngineOutput
    
    # Consolidated predictions
    final_data: Dict[str, Optional[str]]  # medicine, batch, expiry, etc.
    final_form: PackagingForm
    final_risk_score: int  # 0-100
    final_risk_level: RiskLevel
    
    # Traceability
    execution_trace: List[PipelineExecutionTrace]
    images_processed: int
    total_processing_time_seconds: float
    
    # Backward compatibility
    backward_compatibility_data: Dict[str, Any]
```

**Key Methods:**
- `to_dict()` — Convert to dictionary
- `to_json()` — Full JSON export for logging

---

## Usage

### New Modular Code
```python
from pipeline_orchestrator import PipelineOrchestrator
from pipeline_schemas import MediShieldPipelineOutput

orchestrator = PipelineOrchestrator(classifier_model_path="model.pt")
output = orchestrator.process_medicine_images(["img1.jpg", "img2.jpg"])

# Type-safe access
print(output.final_risk_score)
print(output.final_data["batch_number"])
for signal in output.risk_result.signal_components:
    print(signal.name, signal.raw_value)

# Full JSON export
json_str = output.to_json()
```

### Backward Compatible (Old Code Still Works)
```python
from medishield_pipeline_refactored import process_medicine

result = process_medicine(["img1.jpg", "img2.jpg"])
print(result["final_data"])
print(result["risk_score"])
```

### Direct Engine Usage
```python
from ocr_engine import OCREngine
from fusion_engine import FusionEngine

ocr = OCREngine()
ocr_result = ocr.process_multiple_images(["img1.jpg", "img2.jpg"])

fusion = FusionEngine()
fusion_result = fusion.fuse_results(ocr_result)

print(fusion_result.batch_number.final_value)
print(fusion_result.consistency_score)
```

---

## Improvements Summary

| Aspect | Original | Refactored |
|--------|----------|-----------|
| **Modularity** | Monolithic | 5 independent engines |
| **OCR Confidence** | Global field-completeness | Per-field scores |
| **Preprocessing** | Fixed pipeline | Adaptive (CLAHE, denoising) |
| **Fusion** | Simple voting | Weighted agreement + conflicts |
| **Risk Scoring** | Rule-based | Weighted multi-component |
| **Logging** | Minimal | Full execution trace |
| **Type Safety** | Dict chaos | Strict dataclasses |
| **Testability** | Hard | Each engine testable in isolation |
| **Backward Compat** | N/A | 100% transparent |

---

## Testing

**For integration test:**
```bash
python test_refactored_pipeline.py
```

**This validates:**
- ✅ Modular execution flow
- ✅ Structured output schema
- ✅ Backward compatibility
- ✅ Traceability and logging
- ✅ Per-stage confidence scoring
- ✅ JSON serialization

---

## Files Generated

- `pipeline_schemas.py` — Type-safe dataclass schemas
- `ocr_engine.py` — Adaptive OCR extraction
- `fusion_engine.py` — Multi-image consensus
- `validation_engine.py` — Data quality validation
- `classifier_engine.py` — Packaging form classification
- `risk_engine_v2.py` — Advanced risk scoring
- `pipeline_orchestrator.py` — Modular orchestration
- `medishield_pipeline_refactored.py` — Backward compatible adapter
- `test_refactored_pipeline.py` — Integration tests
- [THIS FILE] `REFACTORED_ARCHITECTURE.md` — Documentation

---

## Next Steps

1. **Evaluation Integration** — Existing evaluation harness works transparently
2. **Model Fine-Tuning** — Can now improve individual engines independently
3. **Deployment** — Each engine can be versioned and deployed separately
4. **Monitoring** — Execution trace enables detailed per-pipeline monitoring
5. **Extension** — Easy to add new validation rules or risk signals

---

## Questions?

See embedded docstrings in each engine file for detailed explanations of algorithms and design choices.
