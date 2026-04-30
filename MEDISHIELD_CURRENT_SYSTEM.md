# MediShield Current System

This file describes the system as it currently exists in the workspace.

## What MediShield Does Today

MediShield is split into two working parts:

1. `medishield_ocr.py`
2. `medishield_classifier.py`

The OCR side extracts medicine metadata from multiple images of the same package.
The classifier side predicts the packaging form of a medicine image.

The full counterfeit-risk engine, batch intelligence graph, and drug advice layer
are still future steps. The current code is focused on extraction, validation,
fusion, and packaging-form classification.

## 1. OCR Pipeline

File: `medishield_ocr.py`

### Current flow

1. Input a list of images for the same medicine.
2. Preprocess each image for OCR.
3. Run Tesseract OCR with multiple page segmentation modes.
4. Decode QR data from the original image when available.
5. Extract structured fields from the OCR text.
6. Validate the extracted fields.
7. Fuse results across multiple images.
8. Return a structured JSON-like dictionary.

### Fields extracted

- `medicine_name`
- `batch_number`
- `expiry_date`
- `mfg_date`
- `manufacturer`
- `qr_data`

### OCR details

- Uses OpenCV preprocessing.
- Tries several Tesseract layouts instead of only one.
- Scores OCR text to pick the most useful result.
- Uses heuristics to locate the medicine name near the top of the label.
- Fallback parsing is used for dates if the labelled pattern is missed.

### Validation

The OCR output is checked for:

- missing fields
- invalid date format
- manufacturing date in the future
- expiry date already passed
- manufacturing date later than expiry date
- OCR text that is too short to trust confidently

### Fusion behavior

Across multiple images, the pipeline:

- normalizes values before voting
- uses weighted majority voting
- tracks field conflicts
- handles `qr_data` separately from core OCR fields
- computes derived OCR confidence and agreement metrics

### Current OCR output shape

The current result includes:

- `final_data`
- `per_image_data`
- `derived_parameters`
- `validation`
- `conflicts`
- `raw_text_combined`

## 2. Visual Classifier

File: `medishield_classifier.py`

### Current flow

1. Discover packaging images from the configured dataset path.
2. Infer labels from folder names.
3. Build a MobileNetV2 classifier.
4. Train in two phases:
   - frozen feature extraction
   - partial fine-tuning
5. Evaluate on validation data.
6. Save model and metadata.

### Target classes

- `Tablet`
- `Capsule`
- `Syrup`
- `Injection`
- `Other`

### Extra classifier utilities

- confusion matrix plotting
- classification report
- single-image prediction
- rolling batch anomaly tracker for packaging-form predictions

## 3. What Is Not Built Yet

The following ideas are part of the bigger MediShield vision but are not yet
implemented as a connected end-to-end product:

- counterfeit risk scoring from OCR + classifier together
- batch behavior intelligence across cities/time
- graph-based anomaly visualization
- drug usage / side-effect lookup
- final user-facing app screen

## 4. How The Current System Should Be Described

The safest description of the current system is:

> MediShield currently performs multi-image OCR extraction, QR decoding,
> validation, and fusion for medicine package metadata, and it also has a
> separate visual classifier for medicine packaging form detection.

This keeps the project honest while still matching the larger MediShield idea.

## 5. Next Build Step

The next logical integration step is to connect:

- OCR confidence
- validation issues
- classifier output

into one unified risk score.

## 6. Evaluation

The current evaluation harness is:

- [medishield_evaluation.py](/d:/Projects/kle%20asteria/medishield_evaluation.py)

The current scoring framework is documented in:

- [MEDISHIELD_EVALUATION_FRAMEWORK.md](/d:/Projects/kle%20asteria/MEDISHIELD_EVALUATION_FRAMEWORK.md)
