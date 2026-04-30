#!/usr/bin/env python3
"""
MediShield proof-layer demo.

Usage:
    python demo.py --images sample1.jpg sample2.jpg sample3.jpg
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from collections import Counter
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from io import StringIO
from typing import Any

import cv2
import numpy as np

from medishield_pipeline import process_medicine


CORE_FIELDS = [
    "medicine_name",
    "batch_number",
    "expiry_date",
    "mfg_date",
    "manufacturer",
]

FIELD_TITLES = {
    "medicine_name": "Medicine Name",
    "batch_number": "Batch Number",
    "expiry_date": "Expiry Date",
    "mfg_date": "MFG Date",
    "manufacturer": "Manufacturer",
}


@contextmanager
def _quiet_run():
    previous_disable = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    buffer = StringIO()
    try:
        with redirect_stdout(buffer), redirect_stderr(buffer):
            yield
    finally:
        logging.disable(previous_disable)


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _ascii_text(value: Any) -> str:
    return _clean_text(value).encode("ascii", "ignore").decode("ascii").strip()


def _normalize_for_field(field_name: str, value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    if field_name == "batch_number":
        return text.upper()
    if field_name in {"expiry_date", "mfg_date"}:
        return text.upper().replace(" ", "")
    if field_name == "manufacturer":
        return text.lower()
    return text.lower()


def _parse_conflict(conflict: str) -> tuple[str, list[str]]:
    text = str(conflict or "")
    field = text.split(" mismatch", 1)[0].strip().lower()
    values = re.findall(r"'([^']+)'", text)
    if not values:
        values = re.findall(r'"([^"]+)"', text)
    return field, values


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _assess_image_quality(image_path: str) -> dict[str, Any]:
    img = cv2.imread(image_path)
    if img is None:
        return {
            "image_path": image_path,
            "available": False,
            "score": 0.0,
            "resolution": 0.0,
            "blur": 0.0,
            "contrast": 0.0,
            "text_density": 0.0,
            "level": "LOW",
        }

    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    contrast = float(gray.std())
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    density = float(np.count_nonzero(255 - binary) / max(binary.size, 1))

    resolution_score = _clamp(min(h, w) / 800.0)
    blur_score = _clamp(lap_var / 250.0)
    contrast_score = _clamp(contrast / 60.0)
    density_score = 1.0 - _clamp(abs(density - 0.12) / 0.12)

    score = round(
        0.25 * resolution_score
        + 0.35 * blur_score
        + 0.20 * contrast_score
        + 0.20 * density_score,
        4,
    )

    if score >= 0.7:
        level = "HIGH"
    elif score >= 0.45:
        level = "MEDIUM"
    else:
        level = "LOW"

    return {
        "image_path": image_path,
        "available": True,
        "score": score,
        "resolution": round(resolution_score, 4),
        "blur": round(blur_score, 4),
        "contrast": round(contrast_score, 4),
        "text_density": round(density, 4),
        "level": level,
    }


def _analyze_failures(ocr_result: dict[str, Any]) -> dict[str, Any]:
    final_data = ocr_result.get("ocr", {}).get("final_data", {}) or {}
    per_image_data = ocr_result.get("ocr", {}).get("per_image_data", []) or []
    derived = ocr_result.get("ocr", {}).get("derived_parameters", {}) or {}
    validation = ocr_result.get("ocr", {}).get("validation", {}) or {}
    conflicts = ocr_result.get("ocr", {}).get("conflicts", []) or []
    raw_text = _clean_text(ocr_result.get("ocr", {}).get("raw_text_combined", ""))

    field_rows: list[dict[str, Any]] = []
    most_failed_field = ""
    most_failed_count = -1

    for field_name in CORE_FIELDS:
        final_value = _normalize_for_field(field_name, final_data.get(field_name, ""))
        image_rows = []
        missing_images = []
        mismatch_images = []

        for idx, image_data in enumerate(per_image_data, start=1):
            value = _normalize_for_field(field_name, image_data.get(field_name, ""))
            row = {
                "image_index": idx,
                "value": _clean_text(image_data.get(field_name, "")),
                "matches_final": bool(value and final_value and value == final_value),
                "is_missing": not bool(value),
            }
            image_rows.append(row)
            if not value:
                missing_images.append(idx)
            elif final_value and value != final_value:
                mismatch_images.append(idx)

        fail_count = len(missing_images) + len(mismatch_images)
        if not final_value and any(row["value"] for row in image_rows):
            fail_count = max(fail_count, len(image_rows))

        if fail_count > most_failed_count:
            most_failed_count = fail_count
            most_failed_field = field_name

        field_rows.append(
            {
                "field": field_name,
                "title": FIELD_TITLES[field_name],
                "final_value": _clean_text(final_data.get(field_name, "")) or "NOT FOUND",
                "fail_count": fail_count,
                "missing_images": missing_images,
                "mismatch_images": mismatch_images,
                "images": image_rows,
            }
        )

    why_failed: list[str] = []
    issues = validation.get("issues", []) if isinstance(validation, dict) else validation
    if not isinstance(issues, list):
        issues = [issues] if issues else []

    if issues:
        why_failed.append("Validation flagged: " + ", ".join(str(issue) for issue in issues[:4]))

    if float(derived.get("ocr_confidence", 0.0)) < 0.35:
        why_failed.append(f"OCR confidence is low ({derived.get('ocr_confidence', 0.0):.2f}).")

    if raw_text and len(raw_text) < 80:
        why_failed.append("Combined OCR text is very short, so the text layer likely missed key regions.")

    if conflicts:
        why_failed.append(f"{len(conflicts)} cross-image conflict(s) were detected.")

    if not why_failed:
        why_failed.append("No major failure signal was detected in this run.")

    conflict_rows: list[dict[str, Any]] = []
    for conflict in conflicts:
        field_name, values = _parse_conflict(conflict)
        field_images = []
        final_value = _normalize_for_field(field_name, final_data.get(field_name, ""))

        for idx, image_data in enumerate(per_image_data, start=1):
            image_value = _normalize_for_field(field_name, image_data.get(field_name, ""))
            field_images.append(
                {
                    "image_index": idx,
                    "value": _clean_text(image_data.get(field_name, "")) or "NOT FOUND",
                    "matches_final": bool(image_value and final_value and image_value == final_value),
                }
            )

        mismatch_images = [item["image_index"] for item in field_images if not item["matches_final"]]
        conflict_rows.append(
            {
                "field": field_name,
                "final_value": _clean_text(final_data.get(field_name, "")) or "NOT FOUND",
                "detected_values": values,
                "mismatch_images": mismatch_images,
                "images": field_images,
            }
        )

    return {
        "most_failed_field": most_failed_field,
        "field_failure_table": field_rows,
        "why_ocr_failed": why_failed,
        "conflict_visualization": conflict_rows,
    }


def _classify_failure_type(quality_score: float, result: dict[str, Any]) -> dict[str, Any]:
    ocr = result.get("ocr", {}) or {}
    risk = result.get("risk", {}) or {}
    derived = ocr.get("derived_parameters", {}) or {}
    validation = ocr.get("validation", {}) or {}
    debug = risk.get("debug_signals", {}) or {}
    raw_signals = debug.get("raw_signals", {}) or {}

    ocr_confidence = float(derived.get("ocr_confidence", 0.0))
    issue_count = int(validation.get("issue_count", 0) or 0)
    conflict_count = int(derived.get("conflict_count", 0) or 0)

    if quality_score < 0.45:
        failure_type = "DATA FAILURE"
        reason = "Input image quality is too weak for reliable extraction."
    elif ocr_confidence < 0.35 or issue_count >= 3:
        failure_type = "OCR FAILURE"
        reason = "Image quality is acceptable, but text extraction is still unstable."
    elif raw_signals.get("consistency_risk", 0.0) > 0.25 or conflict_count > 0:
        failure_type = "LOGIC FAILURE"
        reason = "Extraction succeeded, but field agreement or validation introduced the risk."
    else:
        failure_type = "STABLE"
        reason = "No strong failure signal detected."

    return {
        "type": failure_type,
        "reason": reason,
        "quality_score": round(quality_score, 4),
        "ocr_confidence": round(ocr_confidence, 4),
        "issue_count": issue_count,
        "conflict_count": conflict_count,
    }


def _format_reason_breakdown(result: dict[str, Any]) -> dict[str, Any]:
    risk = result.get("risk", {}) or {}
    debug = risk.get("debug_signals", {}) or {}
    raw_signals = debug.get("raw_signals", {}) or {}
    weighted = debug.get("weighted_contributions_to_100", {}) or {}

    return {
        "risk_score": risk.get("risk_score", 0),
        "status": risk.get("status", "Unknown"),
        "confidence": risk.get("confidence", "Unknown"),
        "raw_signals": raw_signals,
        "weighted_contributions": weighted,
        "explanation": risk.get("explanation", []),
    }


def _print_summary(bundle: dict[str, Any]) -> None:
    final = bundle["final_output"]
    failure = bundle["failure_visualization"]
    breakdown = bundle["reason_breakdown"]
    explanation = [_ascii_text(item) for item in final.get("explanation", [])]

    print("=" * 72)
    print("MEDISHIELD - FINAL DEMO RESULT")
    print("=" * 72)
    print("BEFORE")
    print(f"  risk_score: {final['risk_score']}")
    print(f"  status    : {_ascii_text(final['status'])}")
    print(f"  confidence: {_ascii_text(final['confidence'])}")
    print()

    print("AFTER")
    print(f"  STATUS    : {_ascii_text(final['status']).upper()}")
    print(f"  RISK SCORE: {final['risk_score']} / 100")
    print(f"  CONFIDENCE: {_ascii_text(final['confidence']).upper()}")
    print()

    feasibility = bundle.get("ocr_feasibility", {})
    failure_type = bundle.get("failure_type", {})
    print("OCR FEASIBILITY")
    print(f"  SCORE     : {feasibility.get('average_score', 0.0):.2f} / 1.00")
    print(f"  LEVEL     : {str(feasibility.get('level', 'LOW')).upper()}")
    print(f"  FAILURE   : {str(failure_type.get('type', 'UNKNOWN')).upper()}")
    print(f"  REASON    : {_ascii_text(failure_type.get('reason', ''))}")
    print()

    print("REASONS")
    if explanation:
        for idx, item in enumerate(explanation[:4], start=1):
            print(f"  {idx}. {item}")
    else:
        print("  - No explanation available")

    print()
    print("FAILURE VISUALIZATION")
    print(f"  MOST FAILED FIELD: {failure['most_failed_field'] or 'None'}")
    print("  WHY OCR FAILED:")
    for item in failure["why_ocr_failed"]:
        print(f"    - {_ascii_text(item)}")

    if failure["conflict_visualization"]:
        print("  CONFLICT DETAILS:")
        for conflict in failure["conflict_visualization"]:
            print(f"    - {FIELD_TITLES.get(conflict['field'], conflict['field'])}")
            print(f"      final: {_ascii_text(conflict['final_value'])}")
            if conflict["mismatch_images"]:
                print(f"      mismatch images: {', '.join(str(i) for i in conflict['mismatch_images'])}")
            for image in conflict["images"]:
                marker = "OK" if image["matches_final"] else "MISMATCH"
                print(f"      image {image['image_index']}: {_ascii_text(image['value'])} [{marker}]")
    else:
        print("  CONFLICT DETAILS: none")

    print()
    print("REASON BREAKDOWN")
    raw = breakdown.get("raw_signals", {})
    weighted = breakdown.get("weighted_contributions", {})
    for key, value in raw.items():
        if isinstance(value, bool):
            rendered = "yes" if value else "no"
        elif isinstance(value, (int, float)):
            rendered = f"{value:.4f}"
        else:
            rendered = str(value)
        print(f"  - {key}: {rendered}")
    if weighted:
        print("  - weighted contributions:")
        for key, value in weighted.items():
            print(f"    - {key}: {value:.2f}")

    print()
    print("CLEAN JSON")
    print(json.dumps(bundle, indent=2, ensure_ascii=True))


def run_demo(images: list[str]) -> dict[str, Any]:
    with _quiet_run():
        result = process_medicine(images)

    quality_report = [_assess_image_quality(image) for image in images]
    average_quality = sum(item["score"] for item in quality_report) / max(len(quality_report), 1)

    bundle = {
        "input_images": images,
        "final_output": result.get("final_output", {}),
        "failure_visualization": _analyze_failures(result),
        "ocr_feasibility": {
            "images": quality_report,
            "average_score": round(average_quality, 4),
            "level": "HIGH" if average_quality >= 0.7 else "MEDIUM" if average_quality >= 0.45 else "LOW",
        },
        "failure_type": _classify_failure_type(average_quality, result),
        "reason_breakdown": _format_reason_breakdown(result),
        "ocr": result.get("ocr", {}),
        "classifier": result.get("classifier", {}),
    }
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a clean MediShield demo.")
    parser.add_argument(
        "--images",
        nargs="+",
        required=True,
        help="One or more medicine image paths",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional path to save the demo JSON output",
    )
    args = parser.parse_args()

    bundle = run_demo(args.images)
    _print_summary(bundle)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(bundle, handle, indent=2, ensure_ascii=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
