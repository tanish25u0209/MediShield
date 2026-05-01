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
import sys
from collections import Counter
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    cv2 = None

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    np = None

try:
    from PIL import Image, ImageFilter, ImageStat  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    Image = None
    ImageFilter = None
    ImageStat = None

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from medishield_pipeline import process_medicine


CORE_FIELDS = [
    "medicine_name",
    "batch_number",
    "expiry_date",
    "mfg_date",
    "manufacturer",
]

CORE_PRIORITY_FIELDS = ["medicine_name", "batch_number", "expiry_date"]
SUPPORT_PRIORITY_FIELDS = ["manufacturer", "mfg_date"]

FIELD_TITLES = {
    "medicine_name": "Medicine Name",
    "batch_number": "Batch Number",
    "expiry_date": "Expiry Date",
    "mfg_date": "MFG Date",
    "manufacturer": "Manufacturer",
}

VERDICT_ORDER = ("SAFE", "SUSPICIOUS", "HIGH_RISK")
NORMALIZED_FIELD_KEYS = tuple(CORE_FIELDS)


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
    image_path = str(image_path)
    width = height = 0
    blur_score = 0.0
    contrast_score = 0.0
    density_score = 0.0
    resolution_score = 0.0
    density = 0.0

    if cv2 is not None and np is not None:
        img = cv2.imread(image_path)
        if img is not None:
            h, w = img.shape[:2]
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            contrast = float(gray.std())
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            density = float(np.count_nonzero(255 - binary) / max(binary.size, 1))

            height, width = h, w
            resolution_score = _clamp(min(h, w) / 800.0)
            blur_score = _clamp(lap_var / 250.0)
            contrast_score = _clamp(contrast / 60.0)
            density_score = 1.0 - _clamp(abs(density - 0.12) / 0.12)
    elif Image is not None and ImageStat is not None:
        try:
            with Image.open(image_path) as im:
                width, height = im.size
                gray = im.convert("L")
                stat = ImageStat.Stat(gray)
                contrast = float(stat.stddev[0]) if stat.stddev else 0.0
                blur_probe = gray.filter(ImageFilter.FIND_EDGES) if ImageFilter is not None else gray
                edge_stat = ImageStat.Stat(blur_probe)
                edge_energy = float(edge_stat.mean[0]) if edge_stat.mean else 0.0
                resolution_score = _clamp(min(height, width) / 800.0)
                blur_score = _clamp(edge_energy / 80.0)
                contrast_score = _clamp(contrast / 60.0)
                density = _clamp(1.0 - float(stat.mean[0] if stat.mean else 0.0) / 255.0)
                density_score = 1.0 - _clamp(abs(density - 0.12) / 0.12)
        except Exception:
            width = height = 0

    if not width or not height:
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


def _humanize_rejection_reason(reason: str) -> str:
    text = str(reason or "").strip()
    if not text:
        return "insufficient evidence"
    mapping = {
        "CONSISTENT_CONFLICT": "conflicting values across images",
        "CROSS_CONFLICT_BLOCKED": "conflicting values across images",
        "EVIDENCE_CONTRADICTION": "conflicting values across images",
        "FORMAT_INVALID": "format violation",
        "LOW_OCR_CONFIDENCE": "low OCR confidence",
        "NOISE_DOMINANT": "noise dominated the OCR signal",
        "NOISE_DOMINANCE": "noise dominated the OCR signal",
        "NOISE_FAILURE": "noise dominated the OCR signal",
        "NO_VALID_CANDIDATES": "no valid OCR candidates",
        "INSUFFICIENT_EVIDENCE": "insufficient evidence",
        "WEAK_SIGNAL_REJECTED": "weak signal rejected",
        "SINGLE_IMAGE_DOMINANCE_BLOCKED": "single image dominance blocked",
    }
    return mapping.get(text, text.replace("_", " ").lower())


def _normalize_final_presentation(bundle: dict[str, Any]) -> dict[str, Any]:
    ocr = bundle.get("ocr", {}) or {}
    final_output = bundle.get("final_output", {}) or {}
    ml_insights = bundle.get("ml_insights", {}) or final_output.get("ML_INSIGHTS", {}) or {}
    field_decisions = ocr.get("field_decisions", {}) or {}
    final_data = ocr.get("final_data", {}) or {}

    field_records: list[dict[str, Any]] = []
    for field_name in CORE_FIELDS:
        decision = field_decisions.get(field_name, {}) or {}
        signal_breakdown = dict(decision.get("signal_breakdown", {}) or {})
        field_records.append(
            {
                "field": field_name,
                "state": str(decision.get("state", "") or "").upper(),
                "value": _clean_text(decision.get("value", final_data.get(field_name, ""))),
                "reason": str(decision.get("rejection_reason", "") or "").strip(),
                "failure_mode": str(decision.get("failure_mode", "") or "").strip(),
                "confidence": float(decision.get("confidence_score", 0.0) or 0.0),
                "signal_breakdown": signal_breakdown,
            }
        )

    core_records = [record for record in field_records if record["field"] in CORE_PRIORITY_FIELDS]
    support_records = [record for record in field_records if record["field"] in SUPPORT_PRIORITY_FIELDS]

    core_confirmed = [record for record in core_records if record["state"] == "CONFIRMED" and record["value"]]
    core_rejected = [record for record in core_records if record not in core_confirmed]
    support_confirmed = [record for record in support_records if record["state"] == "CONFIRMED" and record["value"]]
    support_rejected = [record for record in support_records if record not in support_confirmed]

    validation = ocr.get("validation", {}) or {}
    integrity_failed = bool(validation.get("integrity_check_failed", False)) if isinstance(validation, dict) else False
    validation_issues = validation.get("issues", []) if isinstance(validation, dict) else validation
    if not isinstance(validation_issues, list):
        validation_issues = [validation_issues] if validation_issues else []

    conflict_records = [
        record
        for record in core_records
        if record["failure_mode"] == "CONSISTENT_CONFLICT"
        or float(record["signal_breakdown"].get("conflict_score", 0.0) or 0.0) > 0.0
        or float(record["signal_breakdown"].get("semantic_variance_score", 0.0) or 0.0) >= 0.35
    ]
    noise_records = [
        record
        for record in field_records
        if record["failure_mode"] == "NOISE_FAILURE"
        or float(record["signal_breakdown"].get("noise_score", 0.0) or 0.0) >= 0.45
    ]
    format_records = [
        record
        for record in core_records
        if record["failure_mode"] == "FORMAT_VIOLATION"
        or float(record["signal_breakdown"].get("format_validity_score", 1.0) or 1.0) <= 0.0
    ]
    dominance_records = [
        record
        for record in field_records
        if record["failure_mode"] == "SINGLE_IMAGE_DOMINANCE_BLOCKED"
        or bool(record["signal_breakdown"].get("single_image_dominance_blocked", False))
    ]

    if integrity_failed:
        verdict = "SUSPICIOUS"
    elif conflict_records or len(core_rejected) >= 2:
        verdict = "HIGH_RISK"
    elif len(core_confirmed) < len(CORE_PRIORITY_FIELDS) or noise_records or format_records or dominance_records or validation_issues:
        verdict = "SUSPICIOUS"
    else:
        verdict = "SAFE"

    reason_candidates: list[dict[str, Any]] = []
    seen_cause_ids: set[str] = set()

    def add_reason(cause_id: str, severity: str, text: str, signal_key: str, weight: int, field_name: str) -> None:
        if cause_id in seen_cause_ids:
            return
        seen_cause_ids.add(cause_id)
        reason_candidates.append(
            {
                "cause_id": cause_id,
                "severity": severity,
                "text": text,
                "signal_key": signal_key,
                "field": field_name,
                "weight": weight,
            }
        )

    if conflict_records:
        record = conflict_records[0]
        add_reason("CORE_CONFLICT", "HIGH", f"Cross-image conflict detected in {FIELD_TITLES.get(record['field'], record['field'])}.", "semantic_variance_score", 100, record["field"])
    if len(core_rejected) >= 2:
        record = core_rejected[0]
        add_reason("MULTI_REJECTION", "HIGH", "Multiple core fields were rejected, so the scan is not stable enough to trust.", "conflict_score", 95, record["field"])
    if format_records:
        record = format_records[0]
        add_reason("FORMAT_VIOLATION", "HIGH", f"Format violation in {FIELD_TITLES.get(record['field'], record['field'])}.", "format_validity_score", 90, record["field"])
    if dominance_records:
        record = dominance_records[0]
        add_reason("DOMINANCE_BLOCK", "MEDIUM", "Single-image dominance was blocked by the evidence validator.", "single_image_dominance_blocked", 80, record["field"])
    if noise_records:
        record = noise_records[0]
        add_reason("NOISE_PRESSURE", "MEDIUM", f"Low OCR confidence reduced support for {FIELD_TITLES.get(record['field'], record['field'])}.", "noise_score", 70, record["field"])
    if len(core_confirmed) < len(CORE_PRIORITY_FIELDS) and verdict != "HIGH_RISK":
        record = next((r for r in core_records if r["state"] != "CONFIRMED"), core_records[0])
        add_reason("PARTIAL_AGREEMENT", "MEDIUM", "Only partial agreement was found across the core fields.", "cross_image_support_score", 60, record["field"])
    if integrity_failed:
        record = next((r for r in field_records if r["state"] != "CONFIRMED"), field_records[0])
        add_reason("INTEGRITY_DOWNGRADE", "HIGH", "An internal evidence check failed, so the final verdict was downgraded to suspicious.", "decision_state", 96, record["field"])
    if verdict == "SAFE":
        add_reason("FULL_AGREEMENT", "LOW", "All core fields were confirmed with consistent evidence.", "cross_image_support_score", 20, "medicine_name")

    reason_candidates.sort(key=lambda item: (-item["weight"], item["cause_id"]))
    reasons = [f"[{item['severity']}] {item['text']}" for item in reason_candidates[:3]]
    reason_causality = [
        {"reason": f"[{item['severity']}] {item['text']}", "signal": item["signal_key"], "field": item["field"]}
        for item in reason_candidates[:3]
    ]

    confidence_score = round(
        (
            0.40 * (len(core_confirmed) / 3.0)
            + 0.30 * (1.0 - min(1.0, len(noise_records) / max(len(CORE_FIELDS), 1)))
            + 0.30 * (len(core_confirmed + support_confirmed) / max(len(CORE_FIELDS), 1))
        )
        * 100
    )
    confidence_score = max(0, min(100, confidence_score))
    confidence_basis_summary = (
        f"High agreement across {len(core_confirmed)}/3 core fields with {len(noise_records)} noise-affected field(s)"
        if core_confirmed
        else "Low core agreement with noise and rejection pressure"
    )

    confirmed_core = [
        {"field": record["field"], "value": record["value"]}
        for record in sorted(core_confirmed, key=lambda item: CORE_PRIORITY_FIELDS.index(item["field"]))
    ]
    confirmed_support = [
        {"field": record["field"], "value": record["value"]}
        for record in sorted(support_confirmed, key=lambda item: SUPPORT_PRIORITY_FIELDS.index(item["field"]))
    ]
    rejected_core = [
        {"field": record["field"], "reason": _humanize_rejection_reason(record["reason"] or record["failure_mode"] or "INSUFFICIENT_EVIDENCE")}
        for record in sorted(core_rejected, key=lambda item: CORE_PRIORITY_FIELDS.index(item["field"]))
    ]
    rejected_support = [
        {"field": record["field"], "reason": _humanize_rejection_reason(record["reason"] or record["failure_mode"] or "INSUFFICIENT_EVIDENCE")}
        for record in sorted(support_rejected, key=lambda item: SUPPORT_PRIORITY_FIELDS.index(item["field"]))
    ]

    return {
        "FINAL_VERDICT": verdict,
        "KEY_REASONS": reasons[:3],
        "CONFIDENCE_SCORE": confidence_score,
        "CONFIDENCE_BASIS_SUMMARY": confidence_basis_summary,
        "CONFIRMED_FIELDS": confirmed_core + confirmed_support,
        "REJECTED_FIELDS": rejected_core + rejected_support,
        "ML_INSIGHTS": {
            "visual_anomaly_score": float(ml_insights.get("visual_anomaly_score", 0.0) or 0.0),
            "ocr_noise_score": float(ml_insights.get("ocr_noise_score", 0.0) or 0.0),
            "image_quality_score": float(ml_insights.get("image_quality_score", 0.0) or 0.0),
            "packaging_type": str(ml_insights.get("packaging_type", "Unknown") or "Unknown"),
            "packaging_type_confidence": float(ml_insights.get("packaging_type_confidence", 0.0) or 0.0),
            "ml_confidence": float(ml_insights.get("ml_confidence", 0.0) or 0.0),
        },
        "FIELD_PRIORITY": {
            "core": [item["field"] for item in confirmed_core + rejected_core],
            "supporting": [item["field"] for item in confirmed_support + rejected_support],
        },
        "REASON_CAUSALITY": reason_causality,
    }


def _print_summary(bundle: dict[str, Any]) -> None:
    presentation = bundle.get("presentation", {}) or _normalize_final_presentation(bundle)
    verdict = str(presentation.get("FINAL_VERDICT", "SUSPICIOUS") or "SUSPICIOUS").upper()
    confidence = int(presentation.get("CONFIDENCE_SCORE", 0) or 0)
    reasons = [str(item) for item in presentation.get("KEY_REASONS", []) or []]
    confirmed = presentation.get("CONFIRMED_FIELDS", []) or []
    rejected = presentation.get("REJECTED_FIELDS", []) or []
    confidence_basis = str(presentation.get("CONFIDENCE_BASIS_SUMMARY", "") or "").strip()
    ml_insights = presentation.get("ML_INSIGHTS", {}) or {}

    print(f"FINAL_VERDICT: {verdict}")
    print(f"CONFIDENCE: {confidence}/100")
    if confidence_basis:
        print(f"CONFIDENCE_BASIS: {confidence_basis}")
    if ml_insights:
        packaging_type = str(ml_insights.get("packaging_type", "Unknown") or "Unknown")
        packaging_conf = float(ml_insights.get("packaging_type_confidence", 0.0) or 0.0)
        overall_ml_conf = float(ml_insights.get("ml_confidence", 0.0) or 0.0)
        print(
            "ML_INSIGHTS: "
            f"Visual Anomaly {float(ml_insights.get('visual_anomaly_score', 0.0) or 0.0):.2f} | "
            f"OCR Noise {float(ml_insights.get('ocr_noise_score', 0.0) or 0.0):.2f} | "
            f"Image Quality {float(ml_insights.get('image_quality_score', 0.0) or 0.0):.2f} | "
            f"Packaging Type {packaging_type} ({packaging_conf:.2f}) | "
            f"ML Confidence {overall_ml_conf:.2f}"
        )
    print("KEY_REASONS:")
    if reasons:
        for item in reasons[:3]:
            print(f"- {item}")
    else:
        print("- No decisive reason available")
    print("CONFIRMED_FIELDS:")
    if confirmed:
        for item in confirmed:
            print(f"- {FIELD_TITLES.get(item['field'], item['field'])}: {item['value']}")
    else:
        print("- none")
    print("REJECTED_FIELDS:")
    if rejected:
        for item in rejected:
            print(f"- {FIELD_TITLES.get(item['field'], item['field'])}: {item['reason']}")
    else:
        print("- none")


def run_demo(images: list[str]) -> dict[str, Any]:
    if not images:
        raise ValueError("No image paths were provided")

    resolved_images = [str(Path(image).expanduser().resolve()) for image in images]
    missing = [image for image in resolved_images if not Path(image).exists()]
    if missing:
        raise FileNotFoundError("Missing image file(s): " + ", ".join(missing))

    with _quiet_run():
        result = process_medicine(resolved_images)

    quality_report = [_assess_image_quality(image) for image in resolved_images]
    average_quality = sum(item["score"] for item in quality_report) / max(len(quality_report), 1)

    bundle = {
        "input_images": resolved_images,
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
    bundle["presentation"] = _normalize_final_presentation(bundle)
    return bundle


def _collect_input_images(images: list[str], folder: str) -> list[str]:
    candidates: list[str] = []
    if folder:
        folder_path = Path(folder).expanduser()
        if folder_path.is_dir():
            for ext in ("*.jpg", "*.jpeg", "*.png", "*.bmp", "*.tif", "*.tiff", "*.webp"):
                candidates.extend(str(path) for path in sorted(folder_path.glob(ext)))
        elif folder_path.exists():
            candidates.append(str(folder_path))

    for image in images:
        path = Path(image).expanduser()
        if path.is_dir():
            for ext in ("*.jpg", "*.jpeg", "*.png", "*.bmp", "*.tif", "*.tiff", "*.webp"):
                candidates.extend(str(p) for p in sorted(path.glob(ext)))
        else:
            candidates.append(str(path))

    seen: set[str] = set()
    unique: list[str] = []
    for item in candidates:
        resolved = str(Path(item).resolve())
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a clean MediShield demo.")
    parser.add_argument("images", nargs="*", help="One or more medicine image paths")
    parser.add_argument(
        "--folder",
        default="",
        help="Optional folder containing medicine images to scan",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional path to save the demo JSON output",
    )
    args = parser.parse_args()

    image_paths = _collect_input_images(args.images, args.folder)
    if not image_paths:
        raise SystemExit("No image files found. Pass image paths or use --folder.")

    bundle = run_demo(image_paths)
    _print_summary(bundle)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(bundle, handle, indent=2, ensure_ascii=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
