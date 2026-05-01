# MediShield

MediShield is a medicine-packaging analysis project that combines OCR, multi-image fusion, validation, risk scoring, and medicine lookup to help flag suspicious or counterfeit products.

The repository contains two closely related code paths:

- A top-level pipeline used for OCR, evidence fusion, risk scoring, and demo output.
- A FastAPI backend under `kle sheshgiri/backend` with auth, scan, batch history, and medicine lookup endpoints.

## What The System Does

- Extracts medicine name, batch number, expiry date, manufacturer, and related fields from package images.
- Combines multiple images of the same product into one fused result.
- Runs validation and risk scoring to produce a final verdict.
- Looks up medicine metadata and local banned/fake medicine references.
- Stores scan history and auth records in the backend database.

## Repository Layout

- `medishield_ocr.py`: OCR, preprocessing, field extraction, fusion, and confidence logic.
- `evidence_validator.py`: Evidence-based field validation and consensus checks.
- `risk_engine.py`: Risk score, confidence, status mapping, and explanation generation.
- `ml_insights.py`: Image-quality and OCR-noise insights, plus optional packaging analysis.
- `medishield_pipeline.py`: End-to-end glue that connects OCR, insights, and risk scoring.
- `demo.py`: Human-friendly demo output and failure visualization.
- `submit.py`: Submission-ready quick run over the bundled synthetic samples.
- `run.py`: Convenience launcher for the end-to-end pipeline.
- `medishield_classifier.py`: Packaging-form classifier training and inference code.
- `pipeline_schemas.py`: Shared data models for pipeline outputs.
- `medishield_data/`: Synthetic medicine dataset and metadata.
- `samples/`: Example images used for experimentation and demos.
- `kle sheshgiri/backend/`: FastAPI backend, auth, scan API, lookup services, and tests.
- `kle sheshgiri/frontend/asteria frontend/`: Frontend authentication UI prototype.
- `kle sheshgiri/predictor/DEMO/`: Legacy medicine predictor demo assets.

## Core Pipeline

The main pipeline flow is:

`OCR -> Fusion -> Evidence Validation -> Risk Engine -> Final Output`

Run it from the repository root:

```bash
python run.py img1.jpg img2.jpg
```

This prints a structured JSON result for the supplied images.

To use it from Python:

```python
from medishield_pipeline import process_medicine

result = process_medicine(["img1.jpg", "img2.jpg"])
print(result["final_output"])
```

## Demo And Submission

Run the judge-facing demo:

```bash
python demo.py --images img1.jpg img2.jpg img3.jpg
```

Optionally save the full JSON output:

```bash
python demo.py --images img1.jpg img2.jpg img3.jpg --output demo_result.json
```

Run the bundled submission smoke test:

```bash
python submit.py
```

## Backend API

The FastAPI backend lives in `kle sheshgiri/backend/main.py`.

Main endpoints:

- `POST /auth/signup`
- `POST /auth/login`
- `POST /auth/forgot-password`
- `POST /auth/reset-password`
- `POST /scan`
- `GET /predict`
- `POST /batch/record`
- `GET /batch/{batch_number}`

Run the backend from the backend directory:

```bash
cd "kle sheshgiri/backend"
uvicorn main:app --reload
```

## Installation

The repo uses Python dependencies from:

- root pipeline packages in the main environment
- `kle sheshgiri/backend/requirements.txt` for the FastAPI backend

If you are setting up the backend specifically:

```bash
cd "kle sheshgiri/backend"
pip install -r requirements.txt
```

If you are using the top-level pipeline, make sure the OCR and imaging dependencies are installed, including Tesseract OCR on your machine.

## Data And Assets

- `medishield_data/raw/`: synthetic front/back sample sets for medicine packages.
- `medishield_data/metadata.json`: dataset metadata.
- `medishield_classifier.pt`: saved classifier weights.
- `medishield_classifier.metadata.json`: classifier metadata.
- `kle sheshgiri/banneddrugs_1.pdf`: banned-drug reference used by the backend.
- `kle sheshgiri/A-List for Drug Alert March-2020.pdf`: additional drug alert reference.
- `kle sheshgiri/backend/data/`: backend reference datasets.

## Testing

Backend tests are in:

- `kle sheshgiri/backend/tests/test_auth_integration.py`
- `kle sheshgiri/backend/tests/test_scan_integration.py`
- `kle sheshgiri/backend/tests/test_validation.py`
- `kle sheshgiri/backend/tests/test_fusion.py`
- `kle sheshgiri/backend/tests/test_risk_confidence.py`

If you want to run them, use your preferred test runner from the backend directory.

## Notes

- The top-level pipeline is the main runtime path used by `run.py`, `demo.py`, and `submit.py`.
- The backend adds database-backed auth and lookup features on top of the scanning flow.
- Some folders contain archived experiments, sample assets, and generated outputs that are useful for reference but not required for the main runtime path.
