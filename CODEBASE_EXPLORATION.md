# MediShield Codebase Exploration

**Last Updated:** 2026-04-30  
**Scope:** Complete architectural walkthrough of OCR pipeline, fusion logic, risk scoring, and evaluation framework

---

## 1. PIPELINE ARCHITECTURE

### Entry Points

| File | Purpose |
|------|---------|
| [run.py](run.py) | Main CLI entrypoint; wraps `medishield_pipeline.main()` |
| [medishield_pipeline.py](medishield_pipeline.py) | Orchestration glue connecting OCR, classifier, and risk engine |

### Pipeline Flow Diagram

```
User provides images
         ↓
    run.py
         ↓
medishield_pipeline.process_medicine()
         ├─ Images → medishield_ocr.process_medicine_images()
         ├─ Images → medishield_classifier.predict_image() (per image separately)
         ├─ OCR output + Classifier results → risk_engine.run_risk_engine()
         └─ Combine into final output (OCR / Classifier / Risk sections)
```

### Orchestration Details

**File:** [medishield_pipeline.py](medishield_pipeline.py)

**Main function:** `process_medicine(images: list[Any]) -> dict[str, Any]`

**Key steps:**
1. **Image normalization** (`_save_temp_image`): Convert PIL Images / numpy arrays to file paths
2. **OCR processing** (`process_medicine_images`): Extracts metadata from all images
3. **Classifier prediction** (`_predict_classifier`): Predicts packaging form per image, votes for consensus
4. **Risk computation** (`run_risk_engine`): Combines OCR signals, classifier signals, validation issues → risk score

**Output structure:**
```python
{
    "ocr": { # Raw OCR output from medishield_ocr
        "final_data": { ... },
        "per_image_data": [ ... ],
        "derived_parameters": { ... },
        "validation": { ... },
        "conflicts": [ ... ],
        "raw_text_combined": "..."
    },
    "classifier": {
        "predicted_class": "Tablet | Capsule | Syrup | Injection | Other",
        "confidence": 0.0–1.0,
        "per_image": [
            {"predicted_type": "Tablet", "confidence": 0.95, "image_path": "..."},
            ...
        ]
    },
    "risk": {  # Complete risk assessment (see section 4)
        "risk_score": 0–100,
        "status": "Safe | Suspicious | High Risk",
        "confidence": "Low | Medium | High",
        "explanation": [ "message 1", "message 2", ... ],
        "debug_signals": { ... } # (optional, include_debug=True)
    },
    "final_output": {  # Simplified summary for CLI
        "risk_score": 0–100,
        "status": "...",
        "confidence": "...",
        "explanation": [ ... ]
    }
}
```

---

## 2. OCR IMPLEMENTATION

### File: [medishield_ocr.py](medishield_ocr.py)

### Entry Point

```python
def process_medicine_images(images: list) -> dict
```

Returns structured OCR output with per-image fields and fused results.

### OCR Pipeline Stages

#### Stage 1: Image Preprocessing (`preprocess_image`)

**Purpose:** Normalize image for Tesseract OCR

**Operations:**
- **Load (BGR):** File path → PIL Image → numpy array (all converted to BGR)
- **Resize:** Scale to longer edge = 800px (prevents both extreme downsizing and huge overhead)
- **Grayscale:** Remove color channels (OCR works on intensity)
- **Gaussian blur:** 3×3 kernel, σ=0 (denoise salt-and-pepper artifacts before thresholding)
- **Adaptive threshold:** Block size=11, C=2. Uses local neighborhood mean instead of global cutoff (handles uneven lighting/shadows)
- **Morphological dilation:** 1×1 kernel, 1 iteration (slightly thickens thin strokes mistaken for noise)

**Output:** Binary numpy array (0 or 255)

#### Stage 1.5: Region-Based Field Extraction (Attempted)

**File functions:**
- `detect_text_regions(binary_image)` → list of text-dense regions (deprecated)
- `crop_region_for_medicine_name(image_bgr, binary)` → top 25% region
- `crop_region_for_batch_expiry(image_bgr, binary)` → bottom 50% region
- `extract_text_from_region(region_bgr, target_field)` → field-specific Tesseract PSM

**Status:** **DISABLED in production.** See [baseline_phase2_results.json](baseline_phase2_results.json) — region-based extraction lost 100% accuracy on critical fields (batch, expiry). Falls back to simple full-image OCR instead.

#### Stage 2: Text Extraction (`extract_text`)

**Tesseract configuration:**
- **OEM 3:** LSTM engine (most accurate for printed labels)
- **PSM configs tried in order:**
  - PSM 6: Single uniform block of text (default for medicine labels)
  - PSM 11: Sparse text
  - PSM 4: Four-column layout
- **Selection:** Tries all PSMs, picks highest-scoring result using `_ocr_text_score()`

**OCR text score formula:**
```
score = (0.45 × alphanumeric_density) 
      + (0.20 × normalized_line_count)
      + (0.25 × keyword_hits / 6)           # batch, exp, mfg, etc. bonus
      + (0.10 × has_digits_bonus)
```

#### Stage 2.5: QR Decoding (`extract_qr_data`)

**Purpose:** Extract QR code data from original image

**Method:** OpenCV QRCodeDetector (operates on unprocessed image; aggressive OCR preprocessing damages QR patterns)

**Return:** QR string or empty string

#### Stage 3: Text Cleaning (`clean_text`)

**Operations:**
1. Lowercase
2. Collapse multiple whitespace to single space
3. Remove non-printable characters (keep 0x20–0x7E)
4. Remove degree, registered trademark, trademark symbols
5. Replace pipe `|` with `i` (common OCR confusion)

#### Stage 4: Field Extraction (`extract_fields`)

**Targeted regex patterns:**

| Field | Regex | Example Match |
|-------|-------|----------------|
| **Batch** | `batch no\\.:?\\s* [alphanumeric]{3,}` | "BATCH NO: BT2024A" → "BT2024A" |
| **Expiry** | `exp(?:iry)?\\s* (\\d{1,2}/\\d{4})` | "EXP 06/2026" → "06/2026" |
| **MFG** | `mfg\\s* (\\d{1,2}/\\d{4})` | "MFG 06/2024" → "06/2024" |
| **Manufacturer** | `[Company patterns with Ltd/Inc/Pharma]` | "Cipla Ltd" |
| **Medicine Name** | Longest capitalized token cluster, top 6 lines | "Amoxicillin 500mg" |

**Post-processing:** `normalize_extracted_fields()`
- Date normalization: MM/YYYY or MM/YY → MM/YYYY
- Batch: uppercase, remove prefixes
- Manufacturer: title case, remove Ltd/Inc/Pvt suffixes
- Medicine name: title case

#### Stage 5: Validation (`validate_fields`)

**Checks performed:**

| Check | Issue Type | Penalty |
|-------|-----------|---------|
| Missing core field | "medicine_name missing" | +0.15 |
| Invalid date format | "expiry_date_invalid" | +0.15 |
| Mfg date > today | "future manufacturing date" | +0.25 |
| Expiry date < today | "expired" | +0.25 |
| Mfg date > Expiry date | "date ordering invalid" | +0.25 |
| OCR text < 20 chars | "text too short" | +0.10 |

**Validation score:** `max(0.0, 1.0 - total_penalties)`

**Output:** `ValidationResult` dataclass
```python
@dataclass
class ValidationResult:
    validation_score: float      # 0.0–1.0 (higher = more valid)
    issue_count: int
    issues: list[str]
```

#### Stage 5.5: Per-Image Confidence (`compute_confidence`)

**Formula:**
```
confidence = (0.6 × field_ratio) 
           + (0.3 × text_density) 
           + (0.1 × length_bonus)

where:
  field_ratio    = extracted_core_fields / 5
  text_density   = alphanumeric_chars / total_chars_in_raw_ocr
  length_bonus   = min(raw_ocr_length / 200, 1.0)
```

Returns: Float in [0.0, 1.0]

### Data Structures

**File:** [medishield_ocr.py](medishield_ocr.py), lines 28–60

```python
@dataclass
class MedicineFields:
    medicine_name: str = ""
    batch_number: str = ""
    expiry_date: str = ""
    mfg_date: str = ""
    manufacturer: str = ""
    qr_data: str = ""
    confidence: float = 0.0
    raw_text: str = ""

@dataclass
class DerivedParameters:
    agreement_score: float = 0.0         # Avg fraction of images agreeing with final
    consistency_score: float = 0.0       # Batch + expiry + mfg consistency
    conflict_count: int = 0
    missing_field_ratio: float = 0.0     # Missing core fields / 5
    ocr_confidence: float = 0.0          # Blended per-image + agreement

@dataclass
class ValidationResult:
    validation_score: float = 0.0
    issue_count: int = 0
    issues: list[str] = field(default_factory=list)

@dataclass
class FusedResult:
    final_data: MedicineFields = field(default_factory=MedicineFields)
    per_image_data: list[MedicineFields] = field(default_factory=list)
    derived_parameters: DerivedParameters = field(default_factory=DerivedParameters)
    conflicts: list[str] = field(default_factory=list)
    raw_text_combined: str = ""
```

---

## 3. FUSION LOGIC

### File: [medishield_ocr.py](medishield_ocr.py), lines 1000–1100

### Function: `fuse_results(per_image: list[MedicineFields])`

**Purpose:** Combine extraction results from multiple images into one authoritative record

**Algorithm:**

For each core field (batch, expiry, mfg, name, manufacturer, qr):

1. **Collect values + weights:**
   - Values = field values from each image
   - Weights = per-image confidence scores

2. **Weighted Majority Vote** (`_weighted_majority`):
   - Normalize values first (batch→uppercase, dates→MM/YYYY, etc.)
   - For each distinct normalized value: `vote[value] += weights[image_idx]`
   - Winner = value with highest total weight

3. **Conflict Detection:**
   - Distinct normalized values > 1 → conflict recorded
   - Conflict message: `"{field_name} mismatch: {sorted(distinct_values)}"`

4. **Derived Parameters Computed:**

   - **Agreement score:** 
     ```
     For each field with final value:
       agree_count = # images whose normalized value == final_value
       field_agreement = agree_count / total_images
     
     agreement_score = mean(field_agreement for all fields with values)
     ```

   - **Consistency score:**
     ```
     critical_fields = [batch, expiry, manufacturer]
     conflict_free = sum(1 for f in critical_fields if f not in conflicts)
     consistency_score = conflict_free / len(critical_fields)
     ```

   - **OCR Confidence (fusion-level):**
     ```
     mean_conf = mean(per_image_confidence scores)
     ocr_confidence = 0.6 × mean_conf + 0.4 × agreement_score
     ```

   - **Missing field ratio:**
     ```
     missing_count = # core fields with empty value
     missing_field_ratio = missing_count / 5
     ```

   - **Conflict count:** `len(conflicts)`

### Normalization Rules (`_normalize_for_field`)

| Field | Normalization |
|-------|----------------|
| batch_number | UPPERCASE |
| expiry_date, mfg_date | Replace `-` / `.` with `/`, pad month → MM/YYYY |
| manufacturer | Title case |
| qr_data | As-is |
| others | Collapse whitespace |

### QR Handling

- QR conflicts tracked separately (can mismatch with OCR fields)
- If QR is empty across all images: excluded from voting
- If QR data present: creates separate conflict record

---

## 4. RISK SCORING

### File: [risk_engine.py](risk_engine.py)

### Architecture: 6-Stage Pipeline

```
Stage 1: Signal Engineering     → 5 normalized 0–1 risk signals
         ↓
Stage 2: Weighted Risk Model    → Composite score (0–100)
         ↓
Stage 3: Status Mapping         → "Safe" / "Suspicious" / "High Risk"
         ↓
Stage 4: Confidence Engine      → "Low" / "Medium" / "High"
         ↓
Stage 5: Explanation Engine     → Severity-ordered list of messages
         ↓
Stage 6: Output Assembly        → Final JSON dict
```

### Stage 1: Signal Engineering

#### 1.1 Consistency Signal (`compute_consistency_signal`)

**Input:** List of field conflicts from OCR fusion

**Computation:**
```
Field severity tiers:
  - Critical (batch, expiry, drug_name)     → weight 1.0
  - Important (manufacturer, dose)          → weight 0.6
  - Minor (storage, country)                → weight 0.3
  - Unknown                                 → weight 0.35

raw_penalty = Σ conflict_weight(severity)
consistency_signal = min(raw_penalty / 3.0, 1.0)
                     # 3 critical conflicts saturate to 1.0
```

**Returns:** (signal ∈ [0,1], conflict_count)

**Rationale:** Cross-image disagreement on critical fields (batch/expiry) is a strong tamper signal. Minor conflicts (storage conditions) are OCR noise.

#### 1.2 Validation Signal (`compute_validation_signal`)

**Input:** List of validation issues (e.g., "expired", "missing_batch")

**Computation:**
```
For each issue:
  severity = ISSUE_SEVERITY.get(issue_type, 0.35)
  
Probabilistic union (prevents two low issues from adding to 1.0):
  complement = 1.0
  for issue in issues:
    complement *= (1.0 - severity[issue])
  
validation_signal = 1.0 - complement
```

**Issue severity map:**
```python
ISSUE_SEVERITY = {
    "expired": 1.0,
    "expiry_date_invalid": 1.0,
    "missing_expiry": 0.9,
    "missing_batch": 0.7,
    "batch_format_invalid": 0.6,
    "missing_manufacturer": 0.5,
    "dose_out_of_range": 0.8,
    "missing_drug_name": 0.6,
    "missing_composition": 0.4,
    "barcode_unreadable": 0.3,
    "missing_storage_conditions": 0.2,
    "missing_country_of_origin": 0.1,
    # default: 0.35
}
```

**Returns:** signal ∈ [0,1]

#### 1.3 OCR Reliability Signal (`compute_ocr_reliability_signal`)

**Input:** OCR confidence ∈ [0,1]

**Computation:**
```
Base inversion: unreliability = 1 - confidence

Soft knee for very low confidence:
  if confidence < 0.3:
    boost = 0.85 + (0.3 - confidence) / 0.3 × 0.15
    unreliability = min(boost, 1.0)
    # Maps [0, 0.3] → [1.0, 0.85]
  else:
    unreliability = 1 - confidence
```

**Rationale:** Very low OCR (< 30%) is penalized more aggressively; below 30%, unreliability jumps to ≥ 0.85 to prevent quietly accepting garbage.

**Returns:** signal ∈ [0,1]

#### 1.4 Classifier Signal (`compute_classifier_signal`)

**Input:** Predicted class + confidence

**Computation:**
```
ANOMALY_CLASSES = {"anomaly", "unknown", "damaged", "tampered", "counterfeit"}

base_risk = 1 - clip(confidence, 0, 1)
anomaly_boost = 0.3 if predicted_class in ANOMALY_CLASSES else 0.0
classifier_signal = min(base_risk + anomaly_boost, 1.0)
```

**Rationale:** Known legitimate classes (Tablet/Capsule/Syrup) at high confidence → low risk. Unknown / anomaly / tampered flagged by model → boost risk by +0.3.

**Returns:** signal ∈ [0,1]

#### 1.5 QR Signal (`compute_qr_signal`)

**Input:** QR data dict or None

**Computation:**
```
if not qr_data:
  return (0.0, False)  # Not penalized, just unavailable

match_status_map = {
    "full_match": 0.0,
    "partial_match": 0.35,
    "no_match": 1.0,
    "error": 0.5,
    "unknown": 0.3,
}

if "match_ratio" in qr_data:
  ratio = clip(qr_data["match_ratio"], 0, 1)
  signal = 1.0 - ratio
else:
  signal = match_status_map.get(status, 0.3)
```

**Returns:** (signal ∈ [0,1], qr_available ∈ [True, False])

**Rationale:** QR mismatch with OCR is a strong indicator of label substitution.

### Stage 2: Weighted Risk Model

#### Configuration

**File:** [risk_engine.py](risk_engine.py), lines 30–37

```python
RISK_WEIGHTS = {
    "consistency":      0.30,    # Cross-image agreement (strongest weight)
    "validation":       0.25,    # Hard rule violations (expiry, missing fields)
    "ocr_reliability":  0.20,    # OCR quality degrades all downstream signals
    "classifier":       0.15,    # Packaging anomaly detection
    "qr_mismatch":      0.10,    # QR↔label discrepancy (often absent)
}
# Sum = 1.0
```

#### Computation

**Function:** `compute_risk_score(signals: RawSignals)`

```
# If QR unavailable, redistribute its weight proportionally
if not signals.qr_available:
  qr_weight = weights.pop("qr_mismatch")
  for key in weights:
    weights[key] += qr_weight × (weights[key] / sum(weights.values()))

# Weighted linear combination
components = {
    "consistency": weights["consistency"] × signal.consistency,
    "validation": weights["validation"] × signal.validation,
    "ocr_reliability": weights["ocr_reliability"] × signal.ocr_unreliability,
    "classifier": weights["classifier"] × signal.classifier_risk,
    "qr_mismatch": weights["qr_mismatch"] × signal.qr_mismatch,
}

raw_score = sum(components.values())  # [0, 1]
risk_score = int(round(min(raw_score × 100, 100)))
```

**Returns:** (risk_score ∈ [0,100], weighted_components dict)

### Stage 3: Status Mapping

**Function:** `map_status(risk_score: int)`

```python
THRESHOLDS = {
    "safe":        (0,  34),   # Low risk, OCR noise acceptable
    "suspicious":  (35, 64),   # Ambiguous, human review recommended
    "high_risk":   (65, 100),  # Multiple signals or one critical signal
}
```

**Design:** Wide "Suspicious" band is intentional — cheaper to review borderline products than to miss tampered ones.

### Stage 4: Confidence Engine

**Function:** `compute_confidence(image_count, agreement_score, ocr_confidence)`

**Interpretation:** Confidence in the risk assessment itself (not in the product).

**Computation:**
```
image_factor = min((image_count - 1) / 4, 1.0)      # Saturates at 5 images
agreement_factor = clip(agreement_score, 0, 1)
ocr_factor = clip(ocr_confidence, 0, 1)

composite = 0.30 × image_factor 
          + 0.40 × agreement_factor 
          + 0.30 × ocr_factor

if composite >= 0.70:
  confidence = "High"
elif composite >= 0.40:
  confidence = "Medium"
else:
  confidence = "Low"
```

**Rationale:**
- Agreement weight highest (0.40): if images disagree, ground truth unknown
- OCR factor (0.30): low OCR limits all reasoning
- Image factor (0.30): more images reduce scan error

### Stage 5: Explanation Engine

**Function:** `generate_explanations(...)`

**Strategy:** Rule-based message generation, ordered by severity

**Message categories:**

1. **Validation issues** → severity-mapped messages (expired → 1.0, missing field → 0.6–0.9)
2. **Cross-image conflicts**:
   - Critical field conflicts → severity 0.95 + "may indicate label tampering"
   - Other conflicts → severity 0.5 + "could be OCR noise"
3. **OCR reliability**:
   - Very low (< 30%) → severity 0.75 + "unreliable"
   - Moderate (30–55%) → severity 0.45 + "some misreads"
4. **Classifier signal**:
   - Anomaly class → severity 0.80 + "visual anomaly detected"
   - Low confidence (< 50%) → severity 0.40 + "uncertain"
5. **QR mismatch**:
   - No match → severity 1.0 + "strong indicator of tampering"
   - Partial match → severity 0.60
6. **Image count warning**:
   - Single image → severity 0.20 + "cross-image verification unavailable"

**Output:** List of strings sorted by severity (most critical first)

### Stage 6: Output Assembly

**Function:** `run_risk_engine(ocr_output, classifier_output, include_debug=True)`

**Returns:**
```python
{
    "risk_score": int (0–100),
    "status": str ("Safe" | "Suspicious" | "High Risk"),
    "confidence": str ("Low" | "Medium" | "High"),
    "explanation": list[str],
    "debug_signals": {  # (optional, if include_debug=True)
        "raw_signals": {
            "consistency_risk": float,
            "validation_risk": float,
            "ocr_unreliability": float,
            "classifier_risk": float,
            "qr_mismatch": float,
            "qr_available": bool,
        },
        "weighted_contributions_to_100": {
            "consistency": float,
            "validation": float,
            "ocr_reliability": float,
            "classifier": float,
            "qr_mismatch": float,
        },
        "meta": {
            "image_count": int,
            "agreement_score": float,
            "ocr_confidence": float,
            "conflict_count": int,
            "issue_count": int,
            "classifier_class": str,
            "classifier_conf": float,
        },
        "weights_used": dict,
        "thresholds": dict,
    }
}
```

---

## 5. OUTPUT FORMATS

### 5.1 OCR Pipeline Output

**Function:** `process_medicine_images(images)`

```python
{
    "final_data": {
        "medicine_name": str,
        "batch_number": str,
        "expiry_date": str,             # MM/YYYY or MM/YY
        "mfg_date": str,                # MM/YYYY or MM/YY
        "manufacturer": str,
        "qr_data": str,                 # Empty if not found
    },
    "per_image_data": [
        {
            "medicine_name": str,
            "batch_number": str,
            "expiry_date": str,
            "mfg_date": str,
            "manufacturer": str,
            "qr_data": str,
            "confidence": float,        # [0.0, 1.0] per-image confidence
            "raw_text": str,            # Raw OCR string from Tesseract
        },
        # ... one entry per image
    ],
    "derived_parameters": {
        "agreement_score": float,       # [0.0, 1.0] avg cross-image agreement
        "consistency_score": float,     # [0.0, 1.0] critical field consistency
        "conflict_count": int,          # # of fields with disagreement
        "missing_field_ratio": float,   # [0.0, 1.0] missing core fields
        "ocr_confidence": float,        # [0.0, 1.0] fused OCR confidence
    },
    "validation": {
        "validation_score": float,      # [0.0, 1.0] higher = more valid
        "issue_count": int,
        "issues": [
            "expired",
            "missing_batch",
            "barcode_unreadable",
            # ... list of validation issue types
        ]
    },
    "conflicts": [
        "batch_number mismatch: ['BT2024A', 'BT2024B']",
        "expiry_date mismatch: ['06/2026', '06/2027']",
        # ... one per conflicting field
    ],
    "raw_text_combined": str,  # All raw OCR strings joined with "--- IMAGE BREAK ---"
}
```

### 5.2 Classifier Pipeline Output

**Function:** `medishield_classifier.predict_image(image_path, model)`

```python
{
    "predicted_type": str,      # "Tablet" | "Capsule" | "Syrup" | "Injection" | "Other"
    "confidence": float,        # [0.0, 1.0]
}
```

**For multi-image consensus:** Voting by confidence weight
```python
{
    "predicted_class": str,
    "confidence": float,
    "per_image": [
        {"predicted_type": "Tablet", "confidence": 0.93, "image_path": "..."},
        {"predicted_type": "Tablet", "confidence": 0.87, "image_path": "..."},
    ]
}
```

### 5.3 Risk Engine Output

**Function:** `run_risk_engine(ocr_output, classifier_output, include_debug=True)`

See **Section 4, Stage 6** for complete structure.

**Minimal output (include_debug=False):**
```python
{
    "risk_score": int,                  # 0–100
    "status": str,                      # "Safe" | "Suspicious" | "High Risk"
    "confidence": str,                  # "Low" | "Medium" | "High"
    "explanation": list[str],
}
```

### 5.4 End-to-End Pipeline Output

**Function:** `medishield_pipeline.process_medicine(images)`

```python
{
    "ocr": { ... },              # Section 5.1
    "classifier": { ... },       # Section 5.2
    "risk": { ... },             # Section 5.3
    "final_output": {            # Simplified for CLI
        "risk_score": int,
        "status": str,
        "confidence": str,
        "explanation": list[str],
    }
}
```

---

## 6. EVALUATION FRAMEWORK

### File: [medishield_evaluation.py](medishield_evaluation.py)

### Entry Point

```bash
python medishield_evaluation.py --manifest eval_manifest.json [--output results.json]
```

### Manifest Format

**Expected shape (JSON array or JSONL):**

```json
[
    {
        "images": ["path/to/img1.jpg", "path/to/img2.jpg"],
        "ground_truth": {
            "medicine_name": "Amoxicillin",
            "batch_number": "BT2024A",
            "expiry_date": "06/2026",
            "mfg_date": "06/2024",
            "manufacturer": "Cipla Ltd"
        },
        "class_label": "Tablet",
        "expected_validation_flag": false,
        "expected_risk_level": "Safe"
    },
    ...
]
```

### Field Weights

```python
CORE_FIELDS = ["batch_number", "expiry_date", "mfg_date", "medicine_name"]
FIELD_WEIGHTS = {
    "batch_number": 0.4,        # Most critical
    "expiry_date": 0.3,
    "mfg_date": 0.2,
    "medicine_name": 0.1,
}
```

### Metrics Computed

#### 6.1 OCR Evaluation

**Per-field accuracy:**

| Metric | Calculation |
|--------|-------------|
| Exact Match | `is_exact_match(predicted, ground_truth)` |
| Fuzzy Match | Levenshtein similarity + SequenceMatcher |
| Field Score | Weighted avg across core fields using FIELD_WEIGHTS |

**Fuzzy accuracy threshold:** Similarity ≥ 0.8 treated as acceptable

**Aggregate metrics:**
```
- ocr_exact_accuracy: exact matches / total samples
- ocr_fuzzy_accuracy: fuzzy matches (threshold=0.8) / total
- ocr_average_fuzzy_score: mean similarity across all fields
- ocr_weighted_score: field_weights-averaged accuracy
```

#### 6.2 Fusion Evaluation

**Goal:** Fused result > single-image result

**Metrics:**
```
single_image_score = accuracy(single-image extraction)
fused_score = accuracy(fused extraction)
fusion_improvement = fused_score - single_image_score
```

#### 6.3 Classifier Evaluation

**Metrics:**
```
- classifier_accuracy: (correct predictions / total)
- classifier_f1: Macro F1 score
- confusion_matrix: Per-class breakdown
- confidence_calibration: Are high-confidence predictions actually correct?
```

**Confidence bucketing:**
```
For each sample:
  bucket = _bucket_label(confidence, step=0.1)  # "00-10", "10-20", etc.
  buckets[bucket] += 1
  if correct:
    buckets[bucket].correct += 1
```

Build calibration curve: confidence bucket → accuracy in that bucket.

#### 6.4 Validation Evaluation

**Metrics:**
```
- validation_accuracy: correctly flagged/unflagged samples
- true_positive_rate (TPR): flagged bad samples / all bad samples
- false_positive_rate (FPR): flagged good samples / all good samples
- Precision / Recall
```

#### 6.5 End-to-End Risk Classification

**Metrics:**
```
- risk_classification_accuracy: correct status prediction
- Risk level confusion matrix: (predicted vs expected)
  - Expected levels: "Safe" | "Suspicious" | "High Risk"
```

### Error Breakdown

**Failure categories logged per sample:**

| Category | Trigger |
|----------|---------|
| OCR error | Extracted value doesn't match ground truth |
| Parsing error | Regex failed to extract despite visible text |
| Fusion error | Fused result worse than best single image |
| Classifier error | Wrong packaging form predicted |
| Validation error | Incorrectly flagged / not flagged |

### Example Evaluation Report

**File:** [baseline_phase2_results.json](baseline_phase2_results.json)

**Example structure:**
```json
{
    "summary": {
        "total_samples": 50,
        "ocr_exact_accuracy": 0.82,
        "ocr_fuzzy_accuracy": 0.94,
        "classifier_accuracy": 0.88,
        "validation_accuracy": 0.91,
        "risk_classification_accuracy": 0.80
    },
    "ocr_detailed": {
        "batch_number": {
            "exact": 0.80,
            "fuzzy": 0.96,
            "average_similarity": 0.92
        },
        "expiry_date": {...},
        "mfg_date": {...},
        "medicine_name": {...}
    },
    "classifier_detailed": {
        "accuracy": 0.88,
        "f1_macro": 0.86,
        "per_class": {
            "Tablet": {"precision": 0.90, "recall": 0.85, "f1": 0.87},
            "Capsule": {...},
            "Syrup": {...},
            ...
        },
        "confusion_matrix": [[...], [...], ...]
    },
    "errors": [
        {
            "sample_idx": 0,
            "field": "batch_number",
            "predicted": "BT-999",
            "ground_truth": "BT2024A",
            "error_type": "OCR error",
            "similarity": 0.23
        },
        ...
    ]
}
```

### Key Test Files

| File | Purpose |
|------|---------|
| [medishield_evaluation.py](medishield_evaluation.py) | Main evaluation harness |
| [baseline_test.py](baseline_test.py) | Legacy baseline validation |
| [baseline_test_phase2.py](baseline_test_phase2.py) | Phase 2 baseline (region-based OCR comparison) |
| [final_validation.py](final_validation.py) | Final system validation |
| [eval_manifest.template.json](eval_manifest.template.json) | Template for test manifest |
| [make_eval_manifest.py](make_eval_manifest.py) | Utility to generate manifests from raw data |

---

## 7. KEY INTEGRATION POINTS

### How Data Flows

```
User Images
    ↓
medishield_ocr.process_medicine_images()
    ↓ returns OCR dict ↓
                    ↓— final_data (fused fields)
                    ├— per_image_data (individual extractions)
                    ├— derived_parameters (agreement, consistency, confidence)
                    ├— validation (issues found)
                    ├— conflicts (field disagreements)
                    └— raw_text_combined (raw OCR strings)
                    
        [OCR dict] ↓
medishield_classifier.predict_image() ×N, vote
    ↓ returns Classifier dict ↓
        {predicted_class, confidence}
        
            ↓ [Both dicts] ↓
        risk_engine.run_risk_engine()
            ↓ returns Risk dict ↓
        {risk_score, status, confidence, explanation, debug_signals}
        
    ↓ ALL THREE ↓
medishield_pipeline.main() returns: {ocr, classifier, risk, final_output}
```

### Confidence Propagation

1. **Per-image OCR confidence** (Stage 5.5 of OCR):
   - Input: field extraction completeness, text density, text length
   - Output: [0, 1] per image

2. **Fused OCR confidence** (Fusion stage):
   - Input: mean per-image confidence + agreement score
   - Formula: `0.6 × mean_conf + 0.4 × agreement_score`
   - Output: [0, 1] single number for entire image set

3. **Risk confidence** (Stage 4 of Risk engine):
   - Input: # images, agreement score, fused OCR confidence
   - Output: "Low" / "Medium" / "High"
   - Interpretation: confidence **in the risk assessment**, not in the product

### Validation Issue Propagation

```
OCR validation (medishield_ocr.validate_fields)
    ↓ issues list ↓
Risk engine (compute_validation_signal)
    ↓ applies severity weighting ↓
Raw validation signal [0, 1]
    ↓ used in weighted risk model ↓
Contributes 25% to final risk score
```

---

## 8. CLASSIFIER ARCHITECTURE

### File: [medishield_classifier.py](medishield_classifier.py)

### Model: MobileNetV2 Transfer Learning

**Architecture:**
- Base: MobileNetV2 pretrained on ImageNet
- Classification head: `Dropout(0.2) → Linear(1280 → 5)`
- Target classes: `["Tablet", "Capsule", "Syrup", "Injection", "Other"]`

**Training (two-phase):**

1. **Phase 1 (frozen backbone):** 2 epochs, LR=1e-3
   - Feature extractor frozen; only head trained
   - Fast, prevents overfitting on small datasets

2. **Phase 2 (fine-tuning):** 2 epochs, LR=1e-4
   - Unfreeze last 4 MobileNet blocks + head
   - Lower LR to prevent catastrophic forgetting
   - Adapts backbone to medicine packaging domain

**Data augmentation (train set only):**
- Random resize crop (scale 0.85–1.0)
- Random horizontal flip
- Random rotation (±12°)
- Color jitter (brightness 0.2, contrast 0.15, sat 0.1, hue 0.03)

**Loss:** CrossEntropyLoss with class weights (balanced)

**Input size:** 224×224 (ImageNet standard)

### Single-Image Prediction

**Function:** `predict_image(image_path, model)`

**Process:**
1. Load image → PIL
2. Apply validation transform (resize → normalize)
3. Forward pass → logits
4. Argmax + softmax → class + confidence

**Returns:**
```python
{
    "predicted_type": str,     # Class name
    "confidence": float,       # Softmax probability for top class
}
```

### Multi-Image Voting

**Function:** `_predict_classifier(images)` in [medishield_pipeline.py](medishield_pipeline.py)

**Algorithm:**

```python
for each image:
    class, conf = predict_image(image)
    vote_weight[class] += conf
    
best_class = argmax(vote_weight)
avg_confidence = mean(confidences for best_class)
```

**Returns:**
```python
{
    "predicted_class": str,
    "confidence": float,           # Average confidence for winning class
    "per_image": [
        {"predicted_type": ..., "confidence": ..., "image_path": ...},
        ...
    ]
}
```

---

## 9. CONFIGURATION & CONSTANTS

### OCR Configuration

**File:** [medishield_ocr.py](medishield_ocr.py)

| Constant | Value | Purpose |
|----------|-------|---------|
| Resize target | 800px (longer edge) | Balance OCR accuracy vs speed |
| Gaussian blur | 3×3 kernel | Denoise before threshold |
| Adaptive threshold | Block 11, C=2 | Handle uneven lighting |
| Tesseract PSM | 6, 11, 4 (tried in order) | Multiple layout assumptions |
| Confidence weights (fusion) | 0.6 mean, 0.4 agreement | Blend image quality + cross-image agreement |

### Risk Engine Configuration

**File:** [risk_engine.py](risk_engine.py)

| Constant | Value | Purpose |
|----------|-------|---------|
| Consistency weight | 0.30 | Cross-image agreement (strongest signal) |
| Validation weight | 0.25 | Hard rule violations |
| OCR reliability weight | 0.20 | Text extraction quality |
| Classifier weight | 0.15 | Packaging anomaly |
| QR mismatch weight | 0.10 | Label authenticity |
| Safe threshold | 0–34 | Low risk band |
| Suspicious threshold | 35–64 | Ambiguous band |
| High Risk threshold | 65–100 | Critical anomalies |
| Image factor saturation | 5 images | More images don't further reduce uncertainty |

### Classifier Configuration

**File:** [medishield_classifier.py](medishield_classifier.py)

| Constant | Value |
|----------|-------|
| Input size | 224×224 |
| Batch size | 32 |
| Initial epochs | 2 |
| Fine-tune epochs | 2 |
| Initial LR | 1e-3 |
| Fine-tune LR | 1e-4 |
| Val/Train split | 0.2 / 0.8 |
| Unfreeze blocks | Last 4 + head |
| Dropout | 0.2 |

---

## 10. QUICK REFERENCE: KEY FILES & FUNCTIONS

| File | Key Functions | Purpose |
|------|----------------|---------|
| [run.py](run.py) | `main()` | CLI entrypoint |
| [medishield_pipeline.py](medishield_pipeline.py) | `process_medicine()`, `_predict_classifier()` | Orchestration |
| [medishield_ocr.py](medishield_ocr.py) | `process_medicine_images()`, `fuse_results()` | OCR + fusion |
| [medishield_classifier.py](medishield_classifier.py) | `predict_image()`, `load_trained_model()` | Classification |
| [risk_engine.py](risk_engine.py) | `run_risk_engine()`, signal functions | Risk scoring |
| [medishield_evaluation.py](medishield_evaluation.py) | `evaluate()`, metric functions | Testing |

---

## 11. DEPLOYMENT & USAGE

### Single Command End-to-End

```bash
python run.py img1.jpg img2.jpg img3.jpg --output result.json
```

**Outputs to stdout:**
```json
{
    "risk_score": 42,
    "status": "Suspicious",
    "confidence": "Medium",
    "explanation": [
        "🟡 QR code data partially matches the label. Some fields are inconsistent.",
        "🟡 Moderate OCR confidence (58%). Some fields may be misread.",
        ...
    ]
}
```

**If `--output result.json` provided:** Saves full output (ocr + classifier + risk + final_output) to file.

### Running Evaluation

```bash
python medishield_evaluation.py --manifest eval_manifest.json --output report.json
```

**Generates comprehensive evaluation report with per-field accuracy, confusion matrices, and error breakdown.**

---

**End of exploration. For implementation details, refer to the file links above.**

