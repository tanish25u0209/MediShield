from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _as_image_array(image_input: Any) -> np.ndarray | None:
    if isinstance(image_input, np.ndarray):
        return image_input
    if isinstance(image_input, Image.Image):
        return cv2.cvtColor(np.array(image_input.convert("RGB")), cv2.COLOR_RGB2BGR)
    if isinstance(image_input, (str, Path)):
        return cv2.imread(str(image_input))
    return None


def _quality_metrics(image_input: Any) -> dict[str, float]:
    image = _as_image_array(image_input)
    if image is None:
        return {"blur": 0.0, "brightness": 0.0, "contrast": 0.0}

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(gray.mean())
    contrast = float(gray.std())
    return {"blur": blur, "brightness": brightness, "contrast": contrast}


def _image_quality_score(image_input: Any) -> tuple[float, dict[str, float]]:
    metrics = _quality_metrics(image_input)
    blur_score = _clamp(metrics["blur"] / 2200.0)
    brightness_score = 1.0 - _clamp(abs(metrics["brightness"] - 128.0) / 128.0)
    contrast_score = _clamp(metrics["contrast"] / 64.0)
    quality = round(0.45 * blur_score + 0.30 * brightness_score + 0.25 * contrast_score, 4)
    return quality, {
        "blur": round(blur_score, 4),
        "brightness": round(brightness_score, 4),
        "contrast": round(contrast_score, 4),
    }


def _ocr_noise_score(ocr_output: dict[str, Any]) -> tuple[float, dict[str, float]]:
    per_image_data = ocr_output.get("per_image_data", []) or []
    derived = ocr_output.get("derived_parameters", {}) or {}

    confidences: list[float] = []
    empty_count = 0
    density_scores: list[float] = []

    for item in per_image_data:
        raw_text = str(item.get("raw_text", "") or "")
        confidence = float(item.get("confidence", 0.0) or 0.0)
        confidences.append(_clamp(confidence / 100.0))

        if not raw_text.strip():
            empty_count += 1

        alnum_chars = sum(ch.isalnum() for ch in raw_text)
        density_scores.append(_clamp(alnum_chars / max(len(raw_text), 1)))

    mean_conf = sum(confidences) / max(len(confidences), 1)
    empty_ratio = empty_count / max(len(per_image_data), 1)
    text_density = sum(density_scores) / max(len(density_scores), 1)
    ocr_conf = _clamp(float(derived.get("ocr_confidence", 0.0) or 0.0) / 100.0)

    noise_score = round(
        0.40 * (1.0 - ocr_conf)
        + 0.35 * (1.0 - mean_conf)
        + 0.25 * empty_ratio
        + 0.10 * (1.0 - text_density),
        4,
    )
    noise_score = _clamp(noise_score)
    return noise_score, {
        "mean_ocr_confidence": round(mean_conf, 4),
        "empty_ratio": round(empty_ratio, 4),
        "text_density": round(text_density, 4),
    }


def compute_ml_insights(images: list[Any], ocr_output: dict[str, Any]) -> dict[str, Any]:
    image_scores: list[float] = []
    quality_metrics: list[dict[str, float]] = []

    for image in images:
        score, metrics = _image_quality_score(image)
        image_scores.append(score)
        quality_metrics.append(metrics)

    image_quality_score = round(sum(image_scores) / max(len(image_scores), 1), 4)
    ocr_noise_score, ocr_metrics = _ocr_noise_score(ocr_output)
    visual_anomaly_score = _clamp(0.60 * (1.0 - image_quality_score) + 0.40 * ocr_noise_score)
    ml_confidence = _clamp(0.55 * image_quality_score + 0.45 * (1.0 - ocr_noise_score))

    return {
        "image_quality_score": round(image_quality_score, 4),
        "ocr_noise_score": round(ocr_noise_score, 4),
        "visual_anomaly_score": round(visual_anomaly_score, 4),
        "ml_confidence": round(ml_confidence, 4),
        "packaging_type": "Unknown",
        "packaging_type_confidence": 0.0,
        "per_image_quality": quality_metrics,
        "ocr_metrics": ocr_metrics,
    }
