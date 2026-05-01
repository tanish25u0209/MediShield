"""
MediShield Pipeline Glue
========================

Connects the OCR, evidence validation, risk engine, and judge-facing
presentation into one end-to-end production path.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ml_insights import compute_ml_insights
from medishield_ocr import process_medicine_images
from risk_engine import run_risk_engine


def _adapt_ocr_for_risk(ocr_output: dict[str, Any], image_count: int) -> dict[str, Any]:
    derived = ocr_output.get("derived_parameters", {}) or {}
    validation = ocr_output.get("validation", {}) or {}
    conflicts = ocr_output.get("conflicts", []) or []

    return {
        "final_data": ocr_output.get("final_data", {}),
        "per_image_data": ocr_output.get("per_image_data", []),
        "derived_parameters": {
            **derived,
            "image_count": image_count,
        },
        "validation": validation.get("issues", []) if isinstance(validation, dict) else validation,
        "conflicts": conflicts,
        "ocr_confidence": derived.get("ocr_confidence", 0.5),
        "agreement_score": derived.get("agreement_score", 1.0),
        "image_count": image_count,
        "qr_data": None,
    }


def _neutral_classifier_output(image_count: int) -> dict[str, Any]:
    """Return a deterministic classifier placeholder without affecting risk."""
    return {
        "predicted_class": "unknown",
        "confidence": 0.0,
        "per_image": [],
        "image_count": image_count,
        "mode": "bypassed",
    }


def _build_final_output(bundle: dict[str, Any]) -> dict[str, Any]:
    """Use the single judge-facing presentation layer as the final output."""
    presentation = bundle.get("presentation", {}) or {}
    return {
        "FINAL_VERDICT": presentation.get("FINAL_VERDICT", "SUSPICIOUS"),
        "CONFIDENCE_SCORE": presentation.get("CONFIDENCE_SCORE", 0),
        "TOP_3_REASONS": presentation.get("KEY_REASONS", [])[:3],
        "CONFIRMED_FIELDS": presentation.get("CONFIRMED_FIELDS", []),
        "REJECTED_FIELDS": presentation.get("REJECTED_FIELDS", []),
        "CONFIDENCE_BASIS_SUMMARY": presentation.get("CONFIDENCE_BASIS_SUMMARY", ""),
        "ML_INSIGHTS": presentation.get("ML_INSIGHTS", {}),
    }


def process_medicine(images: list[Any]) -> dict[str, Any]:
    """
    Run the current MediShield stack end-to-end.

    Input:
        images: list of image file paths

    Output:
        final combined result with OCR, risk, and judge-facing presentation.
    """
    if not images:
        return {
            "ocr": {},
            "classifier": {},
            "risk": {},
            "final_output": {},
        }

    ocr_result = process_medicine_images(images)
    ml_insights = compute_ml_insights(images, ocr_result)
    classifier_result = _neutral_classifier_output(len(images))
    risk_result = run_risk_engine(
        ocr_output=_adapt_ocr_for_risk(ocr_result, image_count=len(images)),
        classifier_output=classifier_result,
        include_debug=True,
    )

    bundle: dict[str, Any] = {
        "ocr": ocr_result,
        "ml_insights": ml_insights,
        "classifier": classifier_result,
        "risk": risk_result,
        "presentation": {},
    }

    # Import lazily to avoid a circular import with demo.py.
    from demo import _normalize_final_presentation

    bundle["presentation"] = _normalize_final_presentation(bundle)

    return {
        "ocr": ocr_result,
        "ml_insights": ml_insights,
        "classifier": classifier_result,
        "risk": risk_result,
        "presentation": bundle["presentation"],
        "final_output": _build_final_output(bundle),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run MediShield end-to-end on image paths.")
    parser.add_argument("images", nargs="+", help="One or more medicine image paths")
    parser.add_argument("--output", default="", help="Optional path to save the result JSON")
    args = parser.parse_args()

    result = process_medicine(args.images)
    print(json.dumps(result["final_output"], indent=2))

    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
