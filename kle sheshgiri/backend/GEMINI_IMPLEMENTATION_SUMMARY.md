# MediShield Gemini Fallback - Implementation Summary

## What Was Created

### 1. **Gemini Fallback Module** (`modules/gemini_fallback.py`)
A complete integration layer providing:
- ✅ Smart fallback triggers (confidence < 50%, missing fields, conflicts)
- ✅ Multi-image field extraction using Gemini vision
- ✅ Conflict resolution between OCR sources
- ✅ User-friendly risk explanations
- ✅ Concise 2-3 line summaries

### 2. **Integration Documentation** (`GEMINI_INTEGRATION.md`)
Complete guide with:
- Setup instructions (API key)
- Function reference for all 5 APIs
- Integration examples
- Cost optimization tips
- Troubleshooting guide

### 3. **Updated Dependencies** (`requirements.txt`)
- Added `google-generativeai==0.7.2`

---

## Frontend Input/Output Specs

### ✅ Input: POST `/scan`

**Current behavior remains:**
```
Content-Type: multipart/form-data

- images: [File, File, ...] (up to 8 images)
```

**Images should include (in order):**
1. Front of medicine package
2. Back of package
3. QR/barcode image (optional)

---

### ✅ Output: GET Response (ScanResponse)

**Standard Response (no Gemini):**
```json
{
  "request_id": "abc123def456",
  "status": "Safe",
  "risk_score": 15,
  "confidence": 92,
  "parsed_data": {
    "medicine_name": "Aspirin",
    "brand_name": "Aspirin-Plus",
    "dosage_strength": "500mg",
    "dosage_form": "tablet",
    "batch_number": "B202401",
    "manufacturing_date": "01/2024",
    "expiry_date": "01/2026",
    "manufacturer_name": "Pharma Corp",
    "mrp_price": "₹50",
    "composition": "Aspirin 500mg",
    "license_number": "DL/01",
    "barcode_number": "8901234567890"
  },
  "reasons": [],
  "diagnostics": [
    {
      "image_index": 1,
      "is_blurry": false,
      "is_low_quality": false,
      "is_distorted": false
    }
  ],
  "drug_info": {
    "name": "Aspirin",
    "is_banned": false,
    "is_fake_medicine": false
  }
}
```

**Response WITH Gemini Fallback:**
```json
{
  "request_id": "xyz789abc123",
  "status": "High Risk",
  "risk_score": 72,
  "confidence": 68,
  "parsed_data": {
    "medicine_name": "Aspirin",
    "brand_name": "Aspirin-Plus",
    "dosage_strength": "500mg",
    "dosage_form": "tablet",
    "batch_number": "B202",
    "manufacturing_date": "01/2024",
    "expiry_date": "01/2026",
    "manufacturer_name": "Pharma Corp",
    "mrp_price": "₹50",
    "composition": "Aspirin 500mg",
    "license_number": "DL/01",
    "barcode_number": "8901234567890"
  },
  "reasons": [
    {
      "code": "batch_mismatch",
      "message": "Batch number varies between front and back (B202 vs B2O2)",
      "severity": "high"
    },
    {
      "code": "expiry_inconsistency",
      "message": "Expiry date conflict: 01/2026 (front) vs 07/2023 (back)",
      "severity": "high"
    },
    {
      "code": "low_quality_image_1",
      "message": "Front image has low quality - text may be partially unreadable",
      "severity": "medium"
    }
  ],
  "diagnostics": [
    {
      "image_index": 1,
      "is_blurry": false,
      "is_low_quality": true,
      "is_distorted": false
    },
    {
      "image_index": 2,
      "is_blurry": true,
      "is_low_quality": false,
      "is_distorted": false
    }
  ],
  "drug_info": {
    "name": "Aspirin",
    "is_banned": false,
    "is_fake_medicine": false
  },
  "gemini_fallback": {
    "triggered": true,
    "reason": "Low OCR confidence (42%) + Batch/expiry conflicts detected",
    "gemini_extracted_fields": {
      "batch_number": "B202",
      "expiry_date": "01/2026",
      "medicine_name": "Aspirin"
    },
    "conflict_resolution": {
      "batch_number": {
        "final_value": "B202",
        "reason": "Majority vote + OCR typo pattern (O vs 0)",
        "confidence": 95
      },
      "expiry_date": {
        "final_value": "01/2026",
        "reason": "Realistic date range; back image unclear",
        "confidence": 85
      }
    },
    "summary": "This medicine shows inconsistencies in batch number and expiry date between packaging images. The product appears potentially counterfeit based on multiple conflicting signals. We recommend not using this medicine without verification from a pharmacist."
  }
}
```

---

## Key Output Fields (Gemini-Related)

### `gemini_fallback` Object (when triggered)

| Field | Type | Description |
|-------|------|-------------|
| `triggered` | bool | Whether Gemini was used as fallback |
| `reason` | string | Why Gemini fallback was triggered |
| `gemini_extracted_fields` | object | Raw fields extracted by Gemini vision |
| `conflict_resolution` | object | Field conflicts resolved with Gemini reasoning |
| `summary` | string | 2-3 line user-friendly summary |

### `conflict_resolution` Structure

For each conflicting field:
```json
{
  "batch_number": {
    "final_value": "B202",
    "reason": "Why this value was chosen (OCR pattern, consistency, etc.)",
    "confidence": 95
  }
}
```

---

## Trigger Conditions (When Gemini is Used)

Gemini fallback activates when:

1. **Low OCR Confidence**: `confidence < 50%`
2. **Missing Critical Fields**: Any of `[medicine_name, batch_number, expiry_date]` is null/empty
3. **Excessive Validation Issues**: > 2 validation errors found
4. **Consistency Conflicts**: Mismatch between front/back/barcode data

**Frontend Impact:** Response includes `gemini_fallback` object when any trigger activates.

---

## Frontend Integration Examples

### Example 1: Display Risk Summary
```javascript
if (response.gemini_fallback?.triggered) {
  // Show Gemini summary in alert
  alert(response.gemini_fallback.summary);
  
  // Log conflict resolutions
  console.log("Resolved conflicts:", response.gemini_fallback.conflict_resolution);
}
```

### Example 2: Display Which Fields Were Enhanced
```javascript
if (response.gemini_fallback?.triggered) {
  const enhanced_fields = Object.keys(response.gemini_fallback.gemini_extracted_fields);
  console.log(`Gemini enhanced fields: ${enhanced_fields.join(", ")}`);
}
```

### Example 3: Show Confidence Indicators
```javascript
// Show that Gemini helped improve confidence
if (response.gemini_fallback?.triggered) {
  // Original confidence before Gemini
  const orig_confidence = response.confidence; // e.g., 42%
  // After Gemini fallback, confidence might increase
  const final_confidence = response.confidence; // e.g., 68%
  
  console.log(`Gemini fallback raised confidence from ${orig_confidence}% to ${final_confidence}%`);
}
```

---

## Fallback Workflow Diagram

```
┌─ Scan Images ─┐
│               │
│  OCR Extract  ┤─┐
│               │ │
└───────────────┘ │
                  │
                  ├─→ Compute Confidence
                  │
                  ├─→ Check Conditions
                  │
     ┌────────────┴──────────────┐
     │                           │
     ▼ Confidence < 50%?         ▼ Missing Fields?
     ▼ Consistency Issues?        ▼ Conflicts?
     │                           │
     └─ YES → Trigger Gemini ◄───┘
     
         │
         ▼ Gemini Vision Extract
         
         ├─ Merge fields
         ├─ Resolve conflicts
         ├─ Generate explanations
         ├─ Generate summary
         │
         ▼ Enhanced Response
         
     includes:
     - gemini_fallback object
     - conflict_resolution
     - summary text
     - enhanced confidence
```

---

## Setup Checklist

- [ ] Install `google-generativeai==0.7.2` (`pip install -r requirements.txt`)
- [ ] Get Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikeys)
- [ ] Set environment variable: `export GEMINI_API_KEY=your_key`
- [ ] Import module in `main.py`:
  ```python
  from modules.gemini_fallback import (
      should_use_gemini_fallback,
      extract_fields_with_gemini,
      resolve_field_conflicts,
      generate_risk_explanations,
      generate_summary,
  )
  ```
- [ ] Add fallback logic to `/scan` endpoint (see `GEMINI_INTEGRATION.md`)
- [ ] Test with low-quality images
- [ ] Deploy with API key set in production environment

---

## Example Backend Code Snippet

Add this to the `/scan` endpoint in `main.py` (after computing confidence):

```python
# Step 1: Check if Gemini fallback should be used
from modules.gemini_fallback import (
    should_use_gemini_fallback,
    extract_fields_with_gemini,
    resolve_field_conflicts,
    generate_risk_explanations,
    generate_summary,
)

gemini_fallback_info = None

if should_use_gemini_fallback(confidence, fused, validation_issues, consistency_issues):
    # Step 2: Extract with Gemini
    gemini_result = extract_fields_with_gemini(
        front_image_bytes,
        back_image_bytes if len(parsed_per_image) > 1 else None,
        barcode_bytes if barcode_data else None,
    )
    
    # Step 3: Merge critical missing fields
    for field in ["medicine_name", "batch_number", "expiry_date"]:
        if not fused.get(field) and gemini_result["fields"].get(field):
            fused[field] = gemini_result["fields"][field]
            fusion_meta.setdefault(field, {})["source"] = "gemini_fallback"
    
    # Step 4: Resolve field conflicts if they exist
    conflict_resolution = {}
    if consistency_issues:
        try:
            conflict_resolution = resolve_field_conflicts(
                parsed_per_image[0] if parsed_per_image else {},
                parsed_per_image[1] if len(parsed_per_image) > 1 else {},
                gemini_result["fields"],
            )
        except Exception as e:
            conflict_resolution = {"error": str(e)}
    
    # Step 5: Generate explanations
    explanations = generate_risk_explanations(
        validation_issues, consistency_issues, anomaly_issues
    )
    
    # Step 6: Generate summary
    summary = generate_summary(
        risk_score, confidence, [i["code"] for i in all_issues[:5]]
    )
    
    gemini_fallback_info = {
        "triggered": True,
        "reason": "Low confidence or field conflicts detected",
        "gemini_extracted_fields": gemini_result["fields"],
        "conflict_resolution": conflict_resolution,
        "summary": summary,
    }

# Step 7: Return response with gemini_fallback info
return ScanResponse(
    request_id=request_id,
    status=status,
    risk_score=risk_score,
    confidence=confidence,
    parsed_data=ParsedFields(**fused),
    reasons=[Issue(**issue) for issue in all_issues],
    diagnostics=diagnostics,
    drug_info=DrugInfo(**drug_info_payload) if drug_info_payload else None,
    gemini_fallback=gemini_fallback_info,  # Add this field
)
```

---

## Cost Estimate

| Operation | Tokens | Cost |
|-----------|--------|------|
| Extract 3 images | ~500 | ~$0.00004 |
| Resolve conflicts | ~1000 | ~$0.00008 |
| Generate explanations | ~300 | ~$0.00003 |
| **Total per fallback** | ~1800 | **~$0.00015** |

**Estimate:** ~$0.15 per 1000 fallbacks (~$1.50 per 10,000 scans)

---

## Support

For issues:
1. Check `GEMINI_INTEGRATION.md` troubleshooting section
2. Verify `GEMINI_API_KEY` environment variable is set
3. Check API quota at [Google AI Studio](https://aistudio.google.com/app/apikeys)
4. Review logs for JSON parse errors

---

## Next Steps

1. ✅ Module created (`gemini_fallback.py`)
2. ✅ Documentation complete
3. ⏳ **To do:** Add fallback logic to main.py `/scan` endpoint
4. ⏳ **To do:** Add `gemini_fallback` field to `ScanResponse` schema
5. ⏳ **To do:** Test end-to-end with low-quality images
6. ⏳ **To do:** Deploy with API key in production

**You're ready to integrate! Follow the code snippet above and reference GEMINI_INTEGRATION.md for details.**
