"""
MediShield ML Insights
======================

Lightweight, deterministic ML-support layer for interpretability only.
This module does not participate in final truth decisions.
"""

from __future__ import annotations

import os
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _tokenize(text: str) -> list[str]:
    return [token for token in __import__("re").findall(r"[A-Za-z0-9][A-Za-z0-9\-/\.]*", text or "") if token]


def _save_temp_image(image_input: Any, index: int, temp_dir: Path) -> str:
    if isinstance(image_input, str):
        return image_input

    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"medishield_ml_{index:03d}.png"

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


def _materialize_images(images: list[Any]) -> tuple[list[str], list[Path]]:
    temp_dir = Path(tempfile.gettempdir()) / "medishield_ml_insights"
    paths: list[str] = []
    temp_files: list[Path] = []

    for index, image in enumerate(images):
        path = _save_temp_image(image, index, temp_dir)
        paths.append(path)
        if not isinstance(image, str):
            temp_files.append(Path(path))

    return paths, temp_files


def _image_quality_score(image_path: str) -> tuple[float, dict[str, float]]:
    img = cv2.imread(image_path)
    if img is None:
        return 0.0, {"blur": 0.0, "brightness": 0.0, "contrast": 0.0, "noise": 1.0}

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur_raw = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness_raw = float(gray.mean())
    contrast_raw = float(gray.std())
    denoised = cv2.GaussianBlur(gray, (3, 3), 0)
    noise_raw = float(np.mean(np.abs(gray.astype(np.float32) - denoised.astype(np.float32))))

    blur_score = _clamp(blur_raw / 220.0)
    brightness_score = 1.0 - _clamp(abs(brightness_raw - 128.0) / 128.0)
    contrast_score = _clamp(contrast_raw / 64.0)
    noise_score = _clamp(noise_raw / 32.0)

    quality = round(
        0.35 * blur_score
        + 0.25 * brightness_score
        + 0.25 * contrast_score
        + 0.15 * (1.0 - noise_score),
        4,
    )
    metrics = {
        "blur": round(blur_score, 4),
        "brightness": round(brightness_score, 4),
        "contrast": round(contrast_score, 4),
        "noise": round(noise_score, 4),
    }
    return quality, metrics


def _ocr_noise_score(ocr_output: dict[str, Any]) -> tuple[float, dict[str, float]]:
    per_image_data = ocr_output.get("per_image_data", []) or []
    derived = ocr_output.get("derived_parameters", {}) or {}

    confidences: list[float] = []
    empty_count = 0
    token_noise_ratios: list[float] = []
    text_density_scores: list[float] = []

    for item in per_image_data:
        raw_text = str(item.get("raw_text", "") or "")
        confidence = float(item.get("confidence", 0.0) or 0.0)
        confidences.append(_clamp(confidence))

        if not raw_text.strip():
            empty_count += 1

        tokens = _tokenize(raw_text)
        token_count = len(tokens)
        alnum_chars = sum(ch.isalnum() for ch in raw_text)
        text_length = max(len(raw_text), 1)
        text_density_scores.append(_clamp(alnum_chars / max(text_length, 1)))

        noisy_tokens = sum(
            1 for token in tokens if len(token) <= 1 or sum(ch.isalnum() for ch in token) / max(len(token), 1) < 0.6
        )
        token_noise_ratios.append(noisy_tokens / max(token_count, 1))

    mean_conf = sum(confidences) / max(len(confidences), 1)
    empty_ratio = empty_count / max(len(per_image_data), 1)
    text_density = sum(text_density_scores) / max(len(text_density_scores), 1)
    token_noise = sum(token_noise_ratios) / max(len(token_noise_ratios), 1)
    ocr_conf = float(derived.get("ocr_confidence", 0.0) or 0.0)

    noise_score = round(
        0.40 * (1.0 - ocr_conf)
        + 0.25 * (1.0 - mean_conf)
        + 0.20 * empty_ratio
        + 0.15 * (1.0 - text_density) * 0.5
        + 0.15 * token_noise * 0.5,
        4,
    )
    noise_score = _clamp(noise_score)
    metrics = {
        "mean_ocr_confidence": round(mean_conf, 4),
        "empty_ratio": round(empty_ratio, 4),
        "text_density": round(text_density, 4),
        "token_noise": round(token_noise, 4),
    }
    return noise_score, metrics


@lru_cache(maxsize=1)
def _optional_packaging_model():
    try:
        from medishield_classifier import load_trained_model

        model_path = Path("medishield_classifier.pt")
        if not model_path.exists():
            return None
        return load_trained_model()
    except Exception:
        return None


def _packaging_type_prediction(image_paths: list[str]) -> tuple[str, float]:
    model = _optional_packaging_model()
    if model is None:
        return "Unknown", 0.0

    try:
        from medishield_classifier import predict_image
    except Exception:
        return "Unknown", 0.0

    results: list[dict[str, Any]] = []
    for path in image_paths:
        try:
            results.append(predict_image(path, model))
        except Exception:
            continue

    if not results:
        return "Unknown", 0.0

    vote: dict[str, float] = {}
    confidence_sum: dict[str, float] = {}
    count_sum: dict[str, int] = {}

    for result in results:
        label = str(result.get("predicted_type", "Unknown") or "Unknown")
        label = label if label in {"Tablet", "Capsule", "Syrup", "Injection"} else "Unknown"
        confidence = _clamp(float(result.get("confidence", 0.0) or 0.0))
        vote[label] = vote.get(label, 0.0) + confidence
        confidence_sum[label] = confidence_sum.get(label, 0.0) + confidence
        count_sum[label] = count_sum.get(label, 0) + 1

    best_label = max(vote, key=vote.get)
    label_confidence = confidence_sum[best_label] / max(count_sum[best_label], 1)
    return best_label, round(_clamp(label_confidence), 4)


def compute_ml_insights(images: list[Any], ocr_output: dict[str, Any]) -> dict[str, Any]:
    """
    Compute deterministic ML-support signals for explanations only.
    """
    image_paths, temp_files = _materialize_images(images)
    try:
        quality_scores: list[float] = []
        quality_metrics: list[dict[str, float]] = []
        for image_path in image_paths:
            quality, metrics = _image_quality_score(image_path)
            quality_scores.append(quality)
            quality_metrics.append(metrics)

        image_quality_score = round(sum(quality_scores) / max(len(quality_scores), 1), 4)
        image_quality_score = _clamp(image_quality_score)

        ocr_noise_score, ocr_metrics = _ocr_noise_score(ocr_output)

        packaging_type, packaging_conf = _packaging_type_prediction(image_paths)

        visual_anomaly_score = _clamp(
            0.55 * (1.0 - image_quality_score)
            + 0.30 * ocr_noise_score
            + 0.15 * (1.0 - packaging_conf if packaging_type != "Unknown" else 0.5)
        )
        ml_confidence = _clamp(
            0.45 * image_quality_score
            + 0.35 * (1.0 - ocr_noise_score)
            + 0.20 * packaging_conf
        )

        return {
            "visual_anomaly_score": round(visual_anomaly_score, 4),
            "ocr_noise_score": round(ocr_noise_score, 4),
            "image_quality_score": round(image_quality_score, 4),
            "packaging_type": packaging_type,
            "packaging_type_confidence": round(packaging_conf, 4),
            "ml_confidence": round(ml_confidence, 4),
        }
    finally:
        for temp_path in temp_files:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass
        if temp_files:
            try:
                temp_files[0].parent.rmdir()
            except Exception:
                pass
