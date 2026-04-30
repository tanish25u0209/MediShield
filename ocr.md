**MediShield OCR — README**

This document explains what the `medishield_ocr.py` pipeline does, how it works, how to run it, and how to interpret its output.

**File**: [medishield_ocr.py](medishield_ocr.py)

**Overview**
- **Purpose**: Extract structured medicine metadata (medicine name, batch number, expiry date, manufacturing date, manufacturer, QR data) from one or more images of the same package and fuse results to improve reliability.
- **Key features**: multi-image fusion, conflict detection, per-image confidence scoring, lightweight heuristics for label parsing, QR decoding.

**Quick Start**
- **Python deps**: Install required packages:

```bash
pip install pytesseract Pillow opencv-python-headless numpy
# System: make sure Tesseract OCR is installed and on PATH (platform-specific).
```

- **Run demo**: The module contains a synthetic demo. From the repository root run:

```bash
python medishield_ocr.py
```

**API / Usage**
- **Main entry**: call `process_medicine_images(images: list) -> dict` where `images` is a list of file paths, `PIL.Image` objects, or `numpy` arrays.

Example:

```python
from medishield_ocr import process_medicine_images

images = ["photo1.jpg", "photo2.jpg"]
result = process_medicine_images(images)
print(result)
```

**Output format**
- The function returns a dictionary with the following keys:
  - **final_data**: authoritative fields chosen after fusion (`medicine_name`, `batch_number`, `expiry_date`, `mfg_date`, `manufacturer`).
  - **per_image_data**: list of per-image extraction dicts (includes `confidence` and `raw_text`).
  - **derived_parameters**: metrics such as `agreement_score`, `consistency_score`, `conflict_count`, `missing_field_ratio`, `ocr_confidence`.
  - **conflicts**: list of human-readable conflict messages (e.g., field mismatches).
  - **raw_text_combined**: concatenated OCR strings for all images.

Example JSON snippet:

```json
{
  "final_data": {"medicine_name": "Amoxicillin", "batch_number": "BT2024A", "expiry_date": "06/2026", "mfg_date": "06/2024", "manufacturer": "Cipla Ltd"},
  "derived_parameters": {"agreement_score": 0.8, "ocr_confidence": 0.82},
  "conflicts": ["batch_number mismatch: ['BT2024A', 'BT2024B']"]
}
```

**Pipeline stages (detailed)**
- **1) Image loading & preprocessing** (`preprocess_image`)
  - Accepts file path, `PIL.Image`, or `numpy` array.
  - Rescales the image to a target longer edge (~800 px) to stabilise OCR.
  - Converts to grayscale, applies light Gaussian blur, adaptive thresholding, and a small dilation to strengthen strokes.

- **2) OCR extraction** (`extract_text`)
  - Runs Tesseract with several `--psm` modes and picks the best OCR result using a scoring heuristic (`_ocr_text_score`).

- **3) QR decoding** (`extract_qr_data`)
  - Uses OpenCV `QRCodeDetector` on the original image (not the aggressively preprocessed image) to preserve QR patterns.

- **4) Text cleaning** (`clean_text`)
  - Normalises OCR output: lowercasing, collapsing whitespace, removing control chars, small symbol normalization, and common OCR noise fixes.

- **5) Field extraction** (`extract_fields`)
  - Uses regex patterns and heuristics to locate batch numbers, expiry/mfg dates, manufacturer names, and medicine names.
  - Medicine name detection favours title-like lines near the top and ignores date/batch lines.

- **6) Per-image confidence + validation** (`compute_confidence`, `validate_fields`)
  - Confidence blends field completeness, text density, and raw length.
  - `validate_fields` produces a `validation_score` and lists issues (e.g., missing fields, date anomalies).

- **7) Multi-image fusion** (`fuse_results`)
  - Weighted majority voting across images using per-image confidence as weights.
  - Records conflicts where images disagree and computes derived parameters.

**Data structures**
- The code defines dataclasses: `MedicineFields`, `DerivedParameters`, `ValidationResult`, `FusedResult` (see [medishield_ocr.py](medishield_ocr.py) for definitions).

**Design notes & heuristics**
- The implementation intentionally uses conservative, explainable heuristics rather than opaque ML models:
  - Regex patterns tuned for common label formats (batch/lot, exp/mfg patterns).
  - Name heuristics rely on capitalization patterns and placement.
  - OCR config tries multiple `psm` modes and ranks results by a heuristic score.

**Limitations & failure modes**
- Handwritten labels, extreme glare, very low-resolution photos, or heavily stylised packaging may fail.
- The regexes are heuristics and may mis-parse uncommon label formats or non-English text.
- Tesseract accuracy depends heavily on image quality and the system Tesseract installation/version.

**Tuning & extensions**
- Improve OCR accuracy by:
  - Increasing target resolution in `preprocess_image` for higher-quality captures.
  - Adding image deskew and contrast-limited adaptive histogram equalization (CLAHE).
  - Fine-tuning Tesseract `--psm`/`--oem` combos or using a fine-tuned OCR model.

- Improve parsing by:
  - Adding locale-specific regex patterns.
  - Training a lightweight classifier to detect the label region and crop noisy backgrounds.

**Where to look in code**
- Main entry and pipeline orchestration: [medishield_ocr.py](medishield_ocr.py)
- Preprocessing and OCR: `preprocess_image`, `extract_text`.
- Parsing: `extract_fields`, regex constants near the top of the file.
- Fusion: `fuse_results`.

**Running tests / demo**
- The module contains a synthetic demo that exercises fusion logic. Run `python medishield_ocr.py` to view sample output.

**Contact / Next steps**
- If you want, I can:
  - Add a `requirements.txt` and a small `README.md` wrapper.
  - Create a minimal CLI wrapper that accepts a folder of images and prints the fused JSON.
