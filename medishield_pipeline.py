"""
MediShield Pipeline Glue
========================

Connects the existing OCR, classifier, and risk engine into one end-to-end
function without changing the core modules.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from medishield_classifier import load_trained_model, predict_image
from medishield_ocr import process_medicine_images
from risk_engine import run_risk_engine


@lru_cache(maxsize=1)
def _classifier_model():
    return load_trained_model()


def _save_temp_image(image_input: Any, index: int, temp_dir: Path) -> str:
    """Persist a non-path image input so the classifier can read it."""
    if isinstance(image_input, str):
        return image_input

    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"medishield_{index:03d}.png"

    if isinstance(image_input, Image.Image):
        image_input.save(temp_path)
        return str(temp_path)

    if isinstance(image_input, np.ndarray):
        arr = image_input
        if arr.ndim == 2:
            cv2.imwrite(str(temp_path), arr)
        else:
            cv2.imwrite(str(temp_path), cv2.cvtColor(arr, cv2.COLOR_RGB2BGR))
        return str(temp_path)

    raise TypeError(f"Unsupported image type: {type(image_input)}")


def _predict_classifier(images: list[str]) -> dict[str, Any]:
    """
    Run the existing packaging classifier on the provided image paths.

    We keep this intentionally simple: predict each image and pick the
    strongest vote by confidence.
    """
    model = _classifier_model()
    results: list[dict[str, Any]] = []

    for image_path in images:
        result = predict_image(image_path, model)
        result["image_path"] = image_path
        results.append(result)

    if not results:
        return {"predicted_class": "unknown", "confidence": 0.0, "per_image": []}

    vote_weight: dict[str, float] = {}
    confidence_sum: dict[str, float] = {}
    count_sum: dict[str, int] = {}

    for result in results:
        label = result["predicted_type"]
        confidence = float(result["confidence"])
        vote_weight[label] = vote_weight.get(label, 0.0) + confidence
        confidence_sum[label] = confidence_sum.get(label, 0.0) + confidence
        count_sum[label] = count_sum.get(label, 0) + 1

    best_label = max(vote_weight, key=vote_weight.get)
    avg_conf = confidence_sum[best_label] / max(count_sum[best_label], 1)

    return {
        "predicted_class": best_label,
        "confidence": round(avg_conf, 4),
        "per_image": results,
    }


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


def process_medicine(images: list[Any]) -> dict[str, Any]:
    """
    Run the current MediShield stack end-to-end.

    Input:
        images: list of image file paths

    Output:
        final combined result with OCR, classifier, and risk sections.
    """
    if not images:
        return {
            "ocr": {},
            "classifier": {},
            "risk": {},
            "final_output": {},
        }

    temp_dir = Path(tempfile.gettempdir()) / "medishield_pipeline"
    classifier_inputs: list[str] = []
    temp_files: list[Path] = []

    try:
        for idx, image in enumerate(images):
            if isinstance(image, str):
                classifier_inputs.append(image)
            else:
                temp_path = Path(_save_temp_image(image, idx, temp_dir))
                classifier_inputs.append(str(temp_path))
                temp_files.append(temp_path)

        ocr_result = process_medicine_images(images)
        classifier_result = _predict_classifier(classifier_inputs)
        risk_result = run_risk_engine(
            ocr_output=_adapt_ocr_for_risk(ocr_result, image_count=len(images)),
            classifier_output={
                "predicted_class": classifier_result["predicted_class"],
                "confidence": classifier_result["confidence"],
            },
            include_debug=True,
        )
    finally:
        for temp_path in temp_files:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass
        if temp_dir.exists():
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

    return {
        "ocr": ocr_result,
        "classifier": classifier_result,
        "risk": risk_result,
        "final_output": {
            "risk_score": risk_result["risk_score"],
            "status": risk_result["status"],
            "confidence": risk_result["confidence"],
            "explanation": risk_result["explanation"],
        },
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
