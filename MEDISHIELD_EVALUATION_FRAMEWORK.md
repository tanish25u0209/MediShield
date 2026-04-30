# MediShield Evaluation Framework

This framework is the current standard for testing MediShield.

## 1. OCR Evaluation

Measure:

- Exact Match Accuracy: `correct / total`
- Fuzzy Match Accuracy: Levenshtein-style similarity, with `> 80%` treated as acceptable
- Field-Weighted Score:
  - `0.4 x batch`
  - `0.3 x expiry`
  - `0.2 x mfg`
  - `0.1 x name`
- Validation Accuracy: whether invalid cases are flagged correctly

## 2. Fusion Evaluation

Compare:

- Single-image OCR
- Multi-image fused OCR

Goal:

- `fused_score > single_score`

If fusion does not improve results, it is not helping.

## 3. Classifier Evaluation

Keep:

- Accuracy
- Confusion matrix
- F1 score

Add:

- Confidence calibration
  - high confidence should usually be correct
  - low confidence should usually be incorrect

## 4. End-to-End Evaluation

Track these separately:

1. Extraction Accuracy
2. Fusion Accuracy
3. Classification Accuracy
4. System Decision Accuracy

## 5. Error Breakdown

Log each failure as one or more of:

- OCR error
- parsing error
- fusion error
- classifier error

## 6. Current Harness

The evaluation script is:

- [medishield_evaluation.py](/d:/Projects/kle%20asteria/medishield_evaluation.py)

Example:

```bash
python medishield_evaluation.py --manifest eval_manifest.json --output report.json
```

## 7. Manifest Shape

Recommended sample:

```json
{
  "images": ["img1.jpg", "img2.jpg"],
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
}
```

