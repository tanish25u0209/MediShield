# MediShield Architecture at a Glance

## System Overview

```
INPUT: Medicine Package Image(s)
           ↓
      [Image Preprocessing]
           ↓
    ┌─────────────────────────┐
    │   MULTI-IMAGE FUSION    │
    │   - Per-image OCR       │
    │   - Weighted voting     │
    │   - Conflict detection  │
    └─────────────────────────┘
           ↓
    ┌─────────┬─────────┬─────────┐
    ↓         ↓         ↓
   OCR    CLASSIFIER   [Combine]
 Output   Output         ↓
    ↓         ↓    RISK ENGINE
    └─────────┴──────────┤
                         ↓
               Risk Score (0-100)
               Status (Safe/Suspicious/High Risk)
               Confidence (Low/Medium/High)
               Explanation (list of issues)
```

---

## OCR Pipeline (6 Stages)

```
STAGE 1: PREPROCESSING
  Input:  Raw image file/PIL/numpy
  • Load (BGR) → Resize (800px) → Grayscale
  • Gaussian blur (3×3) → Adaptive threshold → Dilate
  Output: Binary image

STAGE 2: TEXT EXTRACTION
  Input:  Binary preprocessed image
  • Tesseract OCR (PSM 6, 11, 4 tried in order)
  • Pick highest-scoring result
  Output: Raw OCR string

STAGE 2.5: QR DECODING
  Input:  Original (non-preprocessed) image
  • OpenCV QRCodeDetector
  Output: QR data (or empty)

STAGE 3: TEXT CLEANING
  Input:  Raw OCR string
  • Lowercase, collapse whitespace, remove symbols
  • Fix pipe→i, zero→O substitutions
  Output: Cleaned text

STAGE 4: FIELD EXTRACTION
  Input:  Cleaned text
  • Regex matching for batch, expiry, mfg, name, manufacturer
  • Normalize: dates→MM/YYYY, batch→UPPERCASE, etc.
  Output: MedicineFields struct

STAGE 5: VALIDATION & CONFIDENCE
  Input:  Extracted fields + raw OCR text
  • Validate: field presence, date logic, expiry status
  • Score confidence: field completeness 60% + text density 30% + text length 10%
  Output: ValidationResult, per-image confidence [0-1]

STAGE 6: MULTI-IMAGE FUSION
  Input:  List of per-image results
  • Weighted majority vote (per field)
  • Detect conflicts (distinct normalized values)
  • Compute: agreement_score, consistency_score, ocr_confidence
  Output: Final fused fields + derived parameters
```

---

## Risk Scoring Pipeline (6 Stages)

```
STAGE 1: SIGNAL ENGINEERING (normalize inputs → five 0-1 signals)
  ┌─────────────────────────────────────────────────────┐
  │ CONSISTENCY_SIGNAL    ← Cross-image field conflicts │
  │   Critical (batch, expiry, name)    weight 1.0      │
  │   Important (manufacturer, dose)    weight 0.6      │
  │   Minor (storage, country)          weight 0.3      │
  │   Formula: Σ conflict_weight / 3.0  [0-1]          │
  ├─────────────────────────────────────────────────────┤
  │ VALIDATION_SIGNAL     ← Hard rule violations        │
  │   Expired / missing_expiry / future_mfg etc.       │
  │   Probabilistic union: 1 - Π(1 - issue_severity)  │
  │   Formula: [0-1]                                   │
  ├─────────────────────────────────────────────────────┤
  │ OCR_RELIABILITY_SIGNAL ← OCR confidence inversion   │
  │   Low confidence (< 0.3) gets boost penalty        │
  │   Formula: 1 - confidence (with soft knee)         │
  ├─────────────────────────────────────────────────────┤
  │ CLASSIFIER_SIGNAL     ← Packaging anomaly risk     │
  │   Unknown/Damaged/Tampered → +0.3 boost           │
  │   Formula: 1 - confidence + anomaly_boost          │
  ├─────────────────────────────────────────────────────┤
  │ QR_MISMATCH_SIGNAL    ← QR ↔ label mismatch       │
  │   Full match: 0.0, Partial: 0.35, No: 1.0         │
  │   Or: 1 - match_ratio if available                │
  └─────────────────────────────────────────────────────┘

STAGE 2: WEIGHTED RISK MODEL (composite score)
  consistency      (0.30) × signal_consistency
  validation       (0.25) × signal_validation
  ocr_reliability  (0.20) × signal_ocr
  classifier       (0.15) × signal_classifier
  qr_mismatch      (0.10) × signal_qr
  ─────────────────────────────────────
  raw_score = Σ (weight × signal)  [0-1]
  risk_score = raw_score × 100     [0-100]

STAGE 3: STATUS MAPPING
  0-34    → Safe
  35-64   → Suspicious
  65-100  → High Risk

STAGE 4: CONFIDENCE ENGINE
  image_factor       = min((image_count - 1) / 4, 1.0)   [0-1]
  agreement_factor   = agreement_score                   [0-1]
  ocr_factor         = ocr_confidence                    [0-1]
  
  composite = 0.30 × image_factor
            + 0.40 × agreement_factor
            + 0.30 × ocr_factor
  
  if composite ≥ 0.70: "High"
  elif composite ≥ 0.40: "Medium"
  else: "Low"

STAGE 5: EXPLANATION ENGINE
  • Rule-based message generation
  • Severity-sorted (most critical first)
  • Covers validation issues, conflicts, OCR quality, classifier flags, QR mismatches

STAGE 6: OUTPUT ASSEMBLY
  {
    "risk_score": 42,
    "status": "Suspicious",
    "confidence": "Medium",
    "explanation": ["msg1", "msg2", ...],
    "debug_signals": {...}  # optional
  }
```

---

## Fusion Algorithm (Weighted Majority Vote)

```
Per each field (batch, expiry, mfg, name, manufacturer):
  
  1. COLLECT
     values = [field_from_image_1, field_from_image_2, ...]
     weights = [confidence_1, confidence_2, ...]  # per-image OCR confidence
  
  2. NORMALIZE
     For each value: normalize_for_field(field_name, value)
     (batch→UPPERCASE, dates→MM/YYYY, manufacturer→Title, etc.)
  
  3. VOTE
     vote = {}
     for value, weight in zip(values, weights):
       if value:  # skip empty
         vote[value] += weight
     
     winner = argmax(vote)  # highest total weight
  
  4. DETECT CONFLICTS
     distinct = count(unique normalized values)
     if distinct > 1:
       conflicts.append(f"{field} mismatch: {sorted(distinct)}")

5. COMPUTE DERIVED PARAMS
   
   agreement_score = mean([
       count(images agreeing with final[field]) / total_images
       for field in non_empty_fields
   ])
   
   consistency_score = count(critical_fields without conflicts)
                       / count(critical_fields)
                     # critical: batch, expiry, manufacturer
   
   ocr_confidence = 0.6 × mean(per_image_confidence)
                  + 0.4 × agreement_score
```

---

## Data Structure Relationships

```
PER-IMAGE LEVEL:
  MedicineFields
  ├─ medicine_name: str
  ├─ batch_number: str
  ├─ expiry_date: str (MM/YYYY)
  ├─ mfg_date: str (MM/YYYY)
  ├─ manufacturer: str
  ├─ qr_data: str
  ├─ confidence: float [0-1]
  └─ raw_text: str

FUSED/DERIVED LEVEL:
  DerivedParameters
  ├─ agreement_score: float [0-1]      ← avg cross-image agreement
  ├─ consistency_score: float [0-1]    ← critical fields no-conflict ratio
  ├─ conflict_count: int               ← # fields with disagreement
  ├─ missing_field_ratio: float [0-1] ← empty core fields / 5
  └─ ocr_confidence: float [0-1]      ← fused OCR confidence

VALIDATION LEVEL:
  ValidationResult
  ├─ validation_score: float [0-1]    ← 1.0 = no issues, 0.0 = critical
  ├─ issue_count: int
  └─ issues: list[str]                ← ["expired", "missing_batch", ...]

RISK SIGNAL LEVEL:
  RawSignals
  ├─ consistency: float [0-1]          ← conflict severity
  ├─ validation: float [0-1]           ← issue severity
  ├─ ocr_unreliability: float [0-1]   ← 1 - ocr_confidence
  ├─ classifier_risk: float [0-1]     ← packaging anomaly risk
  ├─ qr_mismatch: float [0-1]         ← label authenticity risk
  └─ qr_available: bool
```

---

## Key Formulas

### Confidence (OCR Per-Image)
```
field_ratio = extracted_fields / 5
text_density = alphanumeric_chars / total_chars
length_bonus = min(ocr_text_length / 200, 1.0)

confidence = 0.6 × field_ratio + 0.3 × text_density + 0.1 × length_bonus
```

### Confidence (OCR Fused Multi-Image)
```
mean_conf = mean(per_image_confidences)
agreement = mean(cross_image_agreement_per_field)

ocr_confidence = 0.6 × mean_conf + 0.4 × agreement
```

### Consistency Signal
```
critical_weight = 1.0  (batch, expiry, drug_name)
important_weight = 0.6 (manufacturer, dose)
minor_weight = 0.3     (storage, country)

raw_penalty = Σ conflict_weight(severity)
signal = min(raw_penalty / 3.0, 1.0)  # saturates at 3
```

### Validation Signal (Probabilistic Union)
```
complement = 1.0
for issue in issues:
  severity = ISSUE_SEVERITY[issue]
  complement *= (1.0 - severity)

signal = 1.0 - complement
```

### OCR Unreliability Signal
```
if confidence < 0.3:
  boost = 0.85 + (0.3 - confidence) / 0.3 × 0.15
  signal = min(boost, 1.0)  # [0→1.0, 0.3→0.85]
else:
  signal = 1 - confidence
```

### Risk Score (Composite)
```
score = Σ weight[i] × signal[i]  for i in {consistency, validation, ocr, classifier, qr}
      = (if QR unavailable: redistribute its weight)
      
risk_score = int(round(score × 100))  [0-100]
```

### Confidence (in risk assessment)
```
image_factor = min((image_count - 1) / 4, 1.0)
agreement_factor = agreement_score
ocr_factor = ocr_confidence

composite = 0.30 × image_factor + 0.40 × agreement_factor + 0.30 × ocr_factor

if composite ≥ 0.70: "High"
elif composite ≥ 0.40: "Medium"
else: "Low"
```

---

## Validation Rule Severity

```
Severity 1.0 (Critical):
  ├─ expired
  ├─ expiry_date_invalid
  
Severity 0.9 (Very High):
  ├─ missing_expiry
  
Severity 0.8 (High):
  ├─ dose_out_of_range
  
Severity 0.7 (High):
  ├─ missing_batch
  
Severity 0.6 (Moderate):
  ├─ batch_format_invalid
  ├─ missing_drug_name
  
Severity 0.5 (Moderate):
  ├─ missing_manufacturer
  
Severity 0.4 (Low):
  ├─ missing_composition
  
Severity 0.3 (Low):
  ├─ barcode_unreadable
  
Severity 0.2 (Very Low):
  ├─ missing_storage_conditions
  
Severity 0.1 (Minimal):
  ├─ missing_country_of_origin
```

---

## Risk Status Thresholds

```
Risk Score   Status          Action
0-34         Safe            ✓ Accept / Allow
35-64        Suspicious      ⚠ Flag for human review
65-100       High Risk       🔴 Block / Escalate
```

---

## Classifier Classes

```
Tablet      → Compressed medication (most common)
Capsule     → Soft/hard gelatin capsules
Syrup       → Liquid oral medication
Injection   → Injectable vials/ampoules
Other       → Fallback / unrecognized forms
```

**Architecture:** MobileNetV2 transfer learning
- **Training:** 2 phases (frozen → fine-tuned)
- **Input:** 224×224 RGB
- **Output:** Class probability distribution

---

## File Dependency Graph

```
run.py
  ↓
medishield_pipeline.py
  ├─ medishield_ocr.py
  │  └─ opencv, pytesseract, numpy, PIL
  ├─ medishield_classifier.py
  │  ├─ torch, torchvision
  │  └─ sklearn
  └─ risk_engine.py
     └─ (no external ML deps)

medishield_evaluation.py
  ├─ medishield_ocr.py
  ├─ medishield_classifier.py
  ├─ risk_engine.py
  └─ sklearn, matplotlib
```

---

## Performance Characteristics

| Component | Typical Speed | Dependency |
|-----------|--------------|-----------|
| Image preprocessing | < 100ms | OpenCV |
| Tesseract OCR (1 image) | 200–500ms | Tesseract-OCR binary |
| Field extraction | < 50ms | Python regex |
| Fusion (3 images) | < 10ms | Python list operations |
| Classifier prediction (1 image) | 50–100ms | GPU/CPU, PyTorch |
| Risk scoring | < 5ms | Python arithmetic |
| **Total (3 images)** | **~1–2 seconds** | GPU available? |

---

## Current Limitations & Notes

1. **Region-based OCR:** Disabled in production. Segmented field extraction (top/bottom crops) **lost 100% accuracy** on critical fields vs. simple full-image approach. See [baseline_phase2_results.json](baseline_phase2_results.json).

2. **QR verification:** Not yet connected to risk scoring. QR data is extracted and flagged for conflicts, but detailed QR↔label matching logic is a pending feature.

3. **Single-image confidence reduced:** When only 1 image provided, confidence automatically degraded (image_factor = 0, agreement undefined). This is intentional — cross-image verification is unavailable.

4. **Classifier training data:** Sourced from Kaggle "Mobile-Captured Pharmaceutical Medication Packages" dataset. Generalization to real-world pharmacy images may vary.

5. **Tesseract quality:** Depends on:
   - Local Tesseract installation (Windows: `Program Files/Tesseract-OCR`)
   - Image resolution (ideal: ≥ 200dpi for labels)
   - Lighting and angle (adaptive threshold helps but has limits)

---

## Quick Debugging Checklist

**Issue: Low OCR confidence (<0.3)**
- ✓ Check image resolution (< 224 pixels on longest edge = will fail)
- ✓ Check image lighting (extreme shadows cause thresholding failure)
- ✓ Check Tesseract installation is in PATH or `Program Files`

**Issue: High conflict count**
- ✓ Images of same medicine or different batches?
- ✓ Check image quality consistency (blurry image will mismatch good ones)
- ✓ Manual review of per_image_data to spot OCR errors on specific images

**Issue: Risk score too high for safe product**
- ✓ Check validation issues (expiry past, missing fields)
- ✓ Check classifier confidence (if < 50%, may flag as uncertain)
- ✓ Check QR mismatch status (if flagged, adds significant risk)
- ✓ Debug signals provided in full risk output show component breakdown

---

**For detailed code exploration, see [CODEBASE_EXPLORATION.md](CODEBASE_EXPLORATION.md)**
