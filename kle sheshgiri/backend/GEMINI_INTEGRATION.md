# Google Gemini Fallback Integration Guide

## Overview

The Gemini fallback system provides intelligent vision-based extraction as a secondary validation layer when:
- OCR confidence is **low** (< 50%)
- **Critical fields are missing** (medicine_name, batch_number, expiry_date)
- **Validation issues exceed** threshold
- **Consistency conflicts** between front/back/barcode images exist

---

## Setup

### 1. Get Gemini API Key

1. Go to [Google AI Studio](https://aistudio.google.com/app/apikeys)
2. Click **Create API Key**
3. Copy the key

### 2. Set Environment Variable

**Windows PowerShell:**
```powershell
$env:GEMINI_API_KEY = "your-api-key-here"
cd "d:\Projects\kle asteria\kle sheshgiri\backend"
& "d:/Projects/kle asteria/.venv/Scripts/python.exe" -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**Linux/Mac:**
```bash
export GEMINI_API_KEY="your-api-key-here"
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**Or add to `.env` file (if using python-dotenv):**
```
GEMINI_API_KEY=your-api-key-here
```

### 3. Install Dependencies

```bash
pip install google-generativeai==0.7.2
```

---

## Integration Points

### In `main.py` Scan Endpoint

```python
from modules.gemini_fallback import (
    should_use_gemini_fallback,
    extract_fields_with_gemini,
    resolve_field_conflicts,
    generate_risk_explanations,
    generate_summary,
)

# After computing confidence, validation_issues, and consistency_issues:

if should_use_gemini_fallback(confidence, fused, validation_issues, consistency_issues):
    # Extract with Gemini as fallback
    gemini_result = extract_fields_with_gemini(
        front_image_bytes,
        back_image_bytes,
        barcode_image_bytes  # optional
    )
    
    # Merge Gemini fields into fused data for critical missing fields
    for field in ["medicine_name", "batch_number", "expiry_date"]:
        if not fused.get(field) and gemini_result["fields"].get(field):
            fused[field] = gemini_result["fields"][field]
            fusion_meta.setdefault(field, {})["source"] = "gemini_fallback"

# Generate user-friendly explanations
explanations = generate_risk_explanations(validation_issues, consistency_issues, anomaly_issues)

# Generate 3-line user summary
summary = generate_summary(risk_score, confidence, [i["code"] for i in all_issues])
```

---

## API Functions

### 1. `should_use_gemini_fallback()`

**Args:**
- `ocr_confidence` (float): Confidence score 0-100
- `parsed_fields` (dict): Extracted field data
- `validation_issues` (list): Validation error dicts
- `consistency_issues` (list): Consistency mismatch dicts

**Returns:** `bool` - True if Gemini should be used

**Triggers if:**
- OCR confidence < 50%
- Critical fields missing
- > 2 validation issues
- Any consistency conflicts

---

### 2. `extract_fields_with_gemini()`

**Args:**
- `front_image_bytes` (bytes): Front image
- `back_image_bytes` (bytes, optional): Back image
- `barcode_image_bytes` (bytes, optional): QR/barcode image

**Returns:**
```json
{
  "source": "gemini_fallback",
  "fields": {
    "medicine_name": "string",
    "brand_name": "string",
    "dosage_strength": "string",
    "dosage_form": "string",
    "batch_number": "string",
    "manufacturing_date": "MM/YYYY",
    "expiry_date": "MM/YYYY",
    "manufacturer_name": "string",
    "mrp_price": "string",
    "composition": "string",
    "license_number": "string",
    "barcode_number": "string",
    "qr_text": "string"
  },
  "confidence": 75,
  "model": "gemini-2.0-flash"
}
```

**Rules Enforced:**
- Only visible text extracted
- Unclear fields return `null`
- No guessing of hidden text
- Dates normalized to MM/YYYY format
- Conflicts noted with alternatives

---

### 3. `resolve_field_conflicts()`

**Args:**
- `source_a` (dict): First source (OCR front)
- `source_b` (dict): Second source (OCR back)
- `source_c` (dict, optional): Third source (Gemini)
- `conflict_fields` (list, optional): Field names with conflicts

**Returns:**
```json
{
  "batch_number": {
    "final_value": "B202",
    "reason": "Majority vote + most consistent with OCR patterns",
    "confidence": 95
  },
  "expiry_date": {
    "final_value": "01/2028",
    "reason": "Only value matching realistic date range",
    "confidence": 85
  }
}
```

---

### 4. `generate_risk_explanations()`

**Args:**
- `validation_issues` (list): Validation dicts
- `consistency_issues` (list): Consistency dicts
- `anomaly_issues` (list): Anomaly dicts

**Returns:** List of user-friendly explanation strings

**Example Output:**
```
[
  "Batch number mismatch between front and back",
  "Expiry date missing on back image",
  "QR code not readable",
  "Manufacturer name spelling differs"
]
```

---

### 5. `generate_summary()`

**Args:**
- `risk_score` (float): Risk score 0-100
- `confidence` (float): Confidence percentage
- `issues` (list): Issue codes

**Returns:** 2-3 line summary string

**Example Output:**
```
"This medicine shows some inconsistencies in packaging details (batch number mismatch, expiry date variants). 
The product appears potentially counterfeit based on multiple signals. 
We recommend not using this medicine without verification from a pharmacist."
```

---

## Frontend Integration

### Input to Backend

**POST `/scan` with fields:**
- `images`: List of up to 8 image files (front, back, QR/barcode)

### Output from Backend (ScanResponse)

```json
{
  "request_id": "abc123...",
  "status": "High Risk",
  "risk_score": 72,
  "confidence": 85,
  "parsed_data": {
    "medicine_name": "Aspirin 500mg",
    "batch_number": "B202",
    "expiry_date": "01/2028",
    "dosage_strength": "500mg",
    "manufacturer_name": "Company XYZ",
    "mrp_price": "₹50"
  },
  "reasons": [
    {
      "code": "batch_mismatch",
      "message": "Batch number varies between front and back images",
      "severity": "high"
    }
  ],
  "diagnostics": [
    {
      "image_index": 1,
      "is_blurry": false,
      "is_low_quality": true,
      "is_distorted": false
    }
  ],
  "drug_info": {
    "name": "Aspirin",
    "is_banned": false,
    "is_fake_medicine": false
  },
  "gemini_summary": "This medicine shows some inconsistencies..."
}
```

---

## Fallback Trigger Examples

### Example 1: Low OCR Confidence
```
OCR confidence: 35%
→ Triggers Gemini extraction
```

### Example 2: Missing Critical Fields
```
OCR extracted: {medicine_name: "Aspirin", batch_number: null, expiry_date: "01/2028"}
→ Batch number missing
→ Triggers Gemini to fill in missing field
```

### Example 3: Consistency Conflicts
```
Front image: batch=B202, expiry=01/2028
Back image: batch=B2O2, expiry=07/2023
→ Conflicts detected
→ Triggers Gemini conflict resolution
```

---

## Cost Optimization

### Gemini API Pricing
- Free tier: 60 requests/minute
- ~$0.075 per million input tokens (gemini-2.0-flash)
- ~$0.30 per million output tokens

### When to Use Fallback
- Only when confidence < 50% (avoids unnecessary API calls)
- Only for high-risk scans (batch anomalies detected)
- Cache results for identical images

### Estimate
- ~500 token avg per 3-image batch extraction
- ~1000 token avg for conflict resolution
- ~300 token avg for explanations
- **Total: ~0.001 per fallback request**

---

## Testing

### Mock Testing (without API key)
```python
# In test files, set GEMINI_API_KEY=test_key or handle gracefully
# Module will raise ValueError if key missing
```

### Integration Test
```bash
# Set API key
export GEMINI_API_KEY=your_key

# Run backend and test /scan endpoint
python -m pytest tests/test_gemini_fallback.py -v
```

---

## Troubleshooting

### Error: `GEMINI_API_KEY not set`
**Solution:** Export the environment variable before starting the server:
```bash
export GEMINI_API_KEY="your-key"
```

### Error: `Unable to parse Gemini response`
**Solution:** Gemini returned non-JSON. Check:
1. API key is valid
2. Images are readable
3. Prompt is clear

### Error: `Rate limit exceeded`
**Solution:** 
- Free tier: max 60 req/min
- Wait and retry
- Upgrade to paid tier for higher limits

---

## Example Full Workflow

```python
# 1. Run main OCR pipeline
text, _ = extract_text(processed)
parsed = parse_fields(text)
confidence = compute_confidence(len(images), parsed, mismatch_count, len(issues))

# 2. Check if fallback is needed
if should_use_gemini_fallback(confidence, parsed, validation_issues, consistency_issues):
    # 3. Extract with Gemini
    gemini_result = extract_fields_with_gemini(front_bytes, back_bytes)
    
    # 4. Merge critical fields
    for field in ["medicine_name", "batch_number"]:
        if not parsed.get(field):
            parsed[field] = gemini_result["fields"].get(field)
    
    # 5. Resolve conflicts if any
    if consistency_issues:
        resolved = resolve_field_conflicts(ocr_front, ocr_back, gemini_result["fields"])
        # Use resolved values
    
    # 6. Generate explanations
    explanations = generate_risk_explanations(validation_issues, consistency_issues, anomaly_issues)
    
    # 7. Generate summary
    summary = generate_summary(risk_score, confidence, issues)

# 8. Return to frontend
return ScanResponse(
    parsed_data=ParsedFields(**parsed),
    reasons=issues,
    gemini_summary=summary  # Add if using fallback
)
```

---

## Best Practices

1. **Use Gemini sparingly** — Only on low-confidence scans
2. **Cache results** — Don't call Gemini twice for same image
3. **Combine sources** — Fuse Gemini output with OCR (don't replace)
4. **Log fallback usage** — Track when/why fallback triggered
5. **Monitor costs** — Set alerts on API usage
6. **Validate output** — Always validate Gemini JSON before using

---

## Next Steps

1. Set `GEMINI_API_KEY` environment variable
2. Install `google-generativeai` package
3. Import `gemini_fallback` module in `main.py`
4. Add fallback logic to `/scan` endpoint
5. Test with low-quality images to trigger fallback
6. Monitor costs and adjust thresholds as needed
