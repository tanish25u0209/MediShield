"""
MediShield OCR Pipeline
========================
Multi-image medicine data extraction engine for counterfeit detection.
Processes multiple images of the same medicine, fuses results, detects
conflicts, and returns structured JSON with confidence and derived parameters.

Dependencies:
    pip install pytesseract Pillow opencv-python-headless numpy

System requirement:
    sudo apt-get install tesseract-ocr
"""

import re
import json
import logging
import os
import statistics
import shutil
from difflib import SequenceMatcher
from pathlib import Path
from datetime import date
from collections import Counter
from dataclasses import dataclass, field, asdict
from typing import Any

import cv2
import numpy as np
import pytesseract
from PIL import Image


def _configure_tesseract() -> None:
    """Point pytesseract at a local Windows install if PATH is not set."""
    if shutil.which("tesseract"):
        return

    candidate = Path("C:/Program Files/Tesseract-OCR/tesseract.exe")
    if candidate.exists():
        pytesseract.pytesseract.tesseract_cmd = str(candidate)

# OCR_GATEWAY
# Only `ocr_core()` is allowed to invoke Tesseract at runtime.
# Everything else in this module must remain post-processing or legacy-only.

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("MediShield.OCR")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class MedicineFields:
    """Structured extraction result for a single image."""
    medicine_name: str = ""
    batch_number: str = ""
    expiry_date: str = ""
    mfg_date: str = ""
    manufacturer: str = ""
    qr_data: str = ""
    confidence: float = 0.0
    medicine_name_confidence: float = 0.0
    batch_confidence: float = 0.0
    expiry_confidence: float = 0.0
    mfg_confidence: float = 0.0
    manufacturer_confidence: float = 0.0
    raw_text: str = ""
    failure_map: dict[str, str] = field(default_factory=dict)
    image_profile: str = "HEAVY_DISTORTION"
    image_profile_score: float = 0.0
    semantic_variance_score: float = 0.0


@dataclass
class DerivedParameters:
    agreement_score: float = 0.0
    consistency_score: float = 0.0
    conflict_count: int = 0
    missing_field_ratio: float = 0.0
    ocr_confidence: float = 0.0


@dataclass
class ValidationResult:
    validation_score: float = 0.0
    issue_count: int = 0
    issues: list[str] = field(default_factory=list)


DEMO_STABILITY_MODE = os.environ.get("MEDISHIELD_DEMO_STABILITY_MODE", "1").strip().lower() not in {"0", "false", "no"}

IMAGE_PROFILE_WEIGHTS = {
    "CLEAN_SIGNAL": 1.00,
    "OCR_NOISY": 0.82,
    "PARTIAL_LABEL": 0.68,
    "HEAVY_DISTORTION": 0.50,
}


def _profile_weight(profile: str) -> float:
    return IMAGE_PROFILE_WEIGHTS.get((profile or "HEAVY_DISTORTION").strip().upper(), 0.50)


def _consolidated_failure_mode(rejection_reason: str, signal_breakdown: dict[str, Any] | None = None) -> str:
    reason = str(rejection_reason or "").strip()
    signal_breakdown = signal_breakdown or {}
    if reason == "FORMAT_INVALID":
        return "FORMAT_VIOLATION"
    if reason in {"CROSS_CONFLICT_BLOCKED", "EVIDENCE_CONTRADICTION"}:
        return "CONSISTENT_CONFLICT"
    if reason in {"LOW_OCR_CONFIDENCE", "NOISE", "NOISE_DOMINANT", "NOISE_DOMINANCE"}:
        return "NOISE_FAILURE"
    if bool(signal_breakdown.get("single_image_dominance_blocked")):
        return "SINGLE_IMAGE_DOMINANCE_BLOCKED"
    if reason in {"NO_VALID_CANDIDATES", "WEAK_SIGNAL_REJECTED", "INSUFFICIENT_EVIDENCE"}:
        return "INSUFFICIENT_EVIDENCE"
    return "INSUFFICIENT_EVIDENCE"


def _semantic_variance_score(values: list[str], field_name: str) -> float:
    normalized = []
    for value in values:
        text = _normalize_for_field(field_name, value)
        if text:
            normalized.append(text)
    if len(normalized) <= 1:
        return 0.0
    pairs = 0
    variance = 0.0
    for i in range(len(normalized)):
        for j in range(i + 1, len(normalized)):
            pairs += 1
            if field_name == "medicine_name":
                similarity = max(
                    SequenceMatcher(None, normalized[i].lower(), normalized[j].lower()).ratio(),
                    SequenceMatcher(
                        None,
                        re.sub(r"[^A-Z0-9]", "", normalized[i].upper()),
                        re.sub(r"[^A-Z0-9]", "", normalized[j].upper()),
                    ).ratio(),
                )
            else:
                similarity = 1.0 if normalized[i] == normalized[j] else SequenceMatcher(None, normalized[i], normalized[j]).ratio()
            variance += 1.0 - similarity
    return round(variance / max(pairs, 1), 4)


def _classify_image_adversarial_profile(fields: MedicineFields, raw_text: str, ocr_confidence: float, trace: dict[str, Any] | None = None) -> tuple[str, float]:
    text = (raw_text or "").strip()
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-/\.]*", text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    symbol_chars = sum(1 for ch in text if not ch.isalnum() and not ch.isspace())
    char_count = max(len(text), 1)
    symbol_ratio = symbol_chars / char_count
    field_presence = sum(
        1
        for value in (
            fields.medicine_name,
            fields.batch_number,
            fields.expiry_date,
            fields.mfg_date,
            fields.manufacturer,
        )
        if str(value or "").strip()
    )
    label_hits = sum(
        1
        for keyword in ("batch", "exp", "expiry", "mfg", "manufact", "medicine")
        if keyword in text.lower()
    )
    line_fragmentation = 1.0 - min(1.0, len(lines) / 6.0)
    token_fragmentation = 1.0 - min(1.0, len(tokens) / 24.0)
    trace_confidence = float((trace or {}).get("ocr_calls", 2) or 2)
    confidence_pressure = 1.0 - min(1.0, max(float(ocr_confidence or 0.0), 0.0))

    if not text or not tokens or symbol_ratio >= 0.42 or confidence_pressure >= 0.72:
        return "HEAVY_DISTORTION", 0.50
    if ocr_confidence < 0.48 or symbol_ratio >= 0.26 or line_fragmentation >= 0.42:
        return "OCR_NOISY", 0.82
    if field_presence <= 2 or label_hits <= 1 or token_fragmentation >= 0.55:
        return "PARTIAL_LABEL", 0.68
    if trace_confidence < 2 or ocr_confidence < 0.7:
        return "OCR_NOISY", 0.82
    return "CLEAN_SIGNAL", 1.0


@dataclass
class FusedResult:
    final_data: MedicineFields = field(default_factory=MedicineFields)
    per_image_data: list[MedicineFields] = field(default_factory=list)
    derived_parameters: DerivedParameters = field(default_factory=DerivedParameters)
    conflicts: list[str] = field(default_factory=list)
    raw_text_combined: str = ""


# ---------------------------------------------------------------------------
# STAGE 1 Ã¢â‚¬â€ Image Preprocessing
# ---------------------------------------------------------------------------

def _load_image_bgr(image_input) -> np.ndarray:
    """Load supported image inputs into an OpenCV BGR array."""
    if isinstance(image_input, str):
        img = cv2.imread(image_input)
        if img is None:
            raise FileNotFoundError(f"Image not found: {image_input}")
        return img
    if isinstance(image_input, Image.Image):
        return cv2.cvtColor(np.array(image_input), cv2.COLOR_RGB2BGR)
    if isinstance(image_input, np.ndarray):
        if image_input.ndim == 2:
            return cv2.cvtColor(image_input, cv2.COLOR_GRAY2BGR)
        return image_input.copy()
    raise TypeError(f"Unsupported image type: {type(image_input)}")


def _resize_long_edge(image_bgr: np.ndarray, long_edge: int) -> np.ndarray:
    h, w = image_bgr.shape[:2]
    if h == 0 or w == 0:
        return image_bgr
    scale = long_edge / max(h, w)
    if abs(scale - 1.0) < 1e-3:
        return image_bgr
    return cv2.resize(
        image_bgr,
        (max(1, int(w * scale)), max(1, int(h * scale))),
        interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA,
    )


def _enhance_ocr_gray(image_bgr: np.ndarray, *, clahe_clip: float = 3.0) -> np.ndarray:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=clahe_clip, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    return cv2.medianBlur(enhanced, 3)


def _binarize_ocr_gray(gray: np.ndarray) -> dict[str, np.ndarray]:
    variants: dict[str, np.ndarray] = {}
    variants["adaptive_gaussian"] = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 4
    )
    variants["adaptive_mean"] = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, 5
    )
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants["otsu"] = otsu
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 1))
    for key, binary in list(variants.items()):
        variants[f"{key}_closed"] = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    return variants


def _ocr_pass_slices(image_bgr: np.ndarray) -> list[dict[str, Any]]:
    h = image_bgr.shape[0]
    half = max(1, h // 2)
    return [
        {"name": "full", "image": image_bgr, "offset_x": 0, "offset_y": 0},
        {"name": "top", "image": image_bgr[:half, :], "offset_x": 0, "offset_y": 0},
        {"name": "bottom", "image": image_bgr[half:, :], "offset_x": 0, "offset_y": half},
    ]


def _ocr_ready_variants(
    image_bgr: np.ndarray,
    passes: tuple[str, ...] = ("full",),
    scales: tuple[float, ...] = (1.5, 2.0, 3.0),
) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = []
    pass_slices = _ocr_pass_slices(image_bgr)
    selected_passes = [item for item in pass_slices if item["name"] in passes]
    for pass_slice in selected_passes:
        crop = pass_slice["image"]
        if crop is None or crop.size == 0:
            continue
        for scale in scales:
            scaled = _resize_long_edge(crop, max(1, int(max(crop.shape[:2]) * scale)))
            gray = _enhance_ocr_gray(scaled)
            binaries = _binarize_ocr_gray(gray)

            def _binary_score(binary: np.ndarray) -> float:
                density = np.count_nonzero(binary) / max(binary.size, 1)
                edge = cv2.Canny(binary, 80, 160)
                edge_density = np.count_nonzero(edge) / max(edge.size, 1)
                balance = 1.0 - abs(0.5 - density) * 2.0
                return _clamp(0.55 * balance + 0.45 * min(edge_density * 5.0, 1.0))

            best_name = max(binaries, key=lambda key: _binary_score(binaries[key]))
            variants.append(
                {
                    "pass_name": pass_slice["name"],
                    "variant_name": best_name,
                    "image": binaries[best_name],
                    "scale": scale,
                    "offset_x": pass_slice["offset_x"],
                    "offset_y": pass_slice["offset_y"],
                }
            )
    return variants


def _preprocess_image_strict(image_input) -> np.ndarray:
    img = _load_image_bgr(image_input)
    img = _resize_long_edge(img, 1400)
    return _enhance_ocr_gray(img)


def _ocr_text_structure_score(text: str) -> float:
    """Score how structured OCR output looks for deterministic fallback selection."""
    text = (text or "").strip()
    if not text:
        return 0.0

    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-/\.]*", text)
    if not tokens:
        return 0.0

    regex_hits = 0
    if _RE_BATCH_STRICT.search(text):
        regex_hits += 1
    if _RE_EXPIRY_STRICT.search(text):
        regex_hits += 1
    if _RE_MFG_STRICT.search(text):
        regex_hits += 1
    if _RE_MANUFACTURER_STRICT.search(text):
        regex_hits += 1
    if _RE_NAME_CANDIDATES.search(text):
        regex_hits += 1

    return float(len(tokens) + (2 * regex_hits) + min(len(text) / 50.0, 5.0))


def _ocr_metrics_from_data(data: dict[str, Any]) -> tuple[str, float, dict[str, Any]]:
    """Convert a single Tesseract result into text plus a confidence proxy."""
    lines: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
    confidences: list[float] = []
    alnum_tokens = 0
    total_tokens = 0

    count = len(data.get("text", []))
    for idx in range(count):
        token = str(data.get("text", [""])[idx] or "").strip()
        if not token:
            continue

        total_tokens += 1
        if re.search(r"[A-Za-z0-9]", token):
            alnum_tokens += 1

        try:
            conf = float(data.get("conf", ["-1"])[idx])
        except Exception:
            conf = -1.0
        if conf >= 0:
            confidences.append(conf)

        key = (
            int(data.get("block_num", [0])[idx]),
            int(data.get("par_num", [0])[idx]),
            int(data.get("line_num", [0])[idx]),
        )
        lines.setdefault(key, []).append(
            {
                "text": token,
                "left": int(data.get("left", [0])[idx]),
                "top": int(data.get("top", [0])[idx]),
                "width": int(data.get("width", [0])[idx]),
                "height": int(data.get("height", [0])[idx]),
            }
        )

    ordered_lines: list[tuple[tuple[int, int, int], list[dict[str, Any]]]] = sorted(
        lines.items(), key=lambda item: item[0]
    )
    text_lines: list[str] = []
    for _, items in ordered_lines:
        items.sort(key=lambda item: item["left"])
        line_text = " ".join(item["text"] for item in items).strip()
        if line_text:
            text_lines.append(line_text)

    raw_text = "\n".join(text_lines).strip()
    avg_tesseract_confidence = (sum(confidences) / len(confidences) / 100.0) if confidences else 0.0
    length_score = min(len(raw_text.strip()) / 120.0, 1.0)
    token_ratio = alnum_tokens / max(total_tokens, 1)
    confidence = _clamp(
        0.50 * avg_tesseract_confidence
        + 0.30 * length_score
        + 0.20 * token_ratio
    )

    trace = {
        "avg_tesseract_confidence": round(avg_tesseract_confidence, 4),
        "length_score": round(length_score, 4),
        "token_ratio": round(token_ratio, 4),
    }
    return raw_text, round(confidence, 4), trace


def _normalize_ocr_token(token: str) -> str:
    token = (token or "").strip()
    if not token:
        return ""
    token = re.sub(r"\s+", "", token)
    token = token.replace("—", "-").replace("–", "-").replace("‐", "-")
    token = token.replace("\\", "/")
    return token.upper()


def _classify_ocr_token(token: str) -> str:
    text = (token or "").strip()
    lower = text.lower()
    if not text:
        return "other"
    if _RE_EXPIRY_STRICT.search(text) or re.fullmatch(r"\d{1,2}[/-]\d{2,4}", text):
        return "expiry"
    if _RE_MFG_STRICT.search(text) or "mfg" in lower or "mfd" in lower:
        return "manufacturer"
    if _RE_BATCH_STRICT.search(text) or any(h in lower for h in ("batch", "lot", "bno", "b/no")):
        return "batch"
    if _RE_MANUFACTURER_STRICT.search(text) or any(h in lower for h in ("ltd", "limited", "pharma", "labs", "healthcare", "company", "corp", "inc", "pvt")):
        return "manufacturer"
    if (
        len(text) >= 4
        and lower not in _GENERIC_OCR_STOPWORDS
        and (
            _RE_NAME_CANDIDATES.search(text)
            or text.isupper()
            or text.istitle()
            or (sum(ch.isalpha() for ch in text) >= 4 and sum(ch.isdigit() for ch in text) == 0)
        )
    ):
        return "medicine"
    return "other"


def _collect_tokens_from_data(
    data: dict[str, Any],
    *,
    stage_name: str,
    offset_y: int = 0,
) -> list[dict[str, Any]]:
    tokens: list[dict[str, Any]] = []
    count = len(data.get("text", []))
    for idx in range(count):
        raw_token = str(data.get("text", [""])[idx] or "").strip()
        token = _accept_ocr_text(raw_token)
        if not token:
            continue
        normalized = _normalize_ocr_token(token)
        if not normalized:
            continue
        try:
            conf = float(data.get("conf", ["-1"])[idx])
        except Exception:
            conf = -1.0
        tokens.append(
            {
                "stage": stage_name,
                "raw": token,
                "normalized": normalized,
                "class": _classify_ocr_token(token),
                "conf": conf,
                "left": int(data.get("left", [0])[idx]),
                "top": int(data.get("top", [0])[idx]) + offset_y,
                "width": int(data.get("width", [0])[idx]),
                "height": int(data.get("height", [0])[idx]),
            }
        )
    return tokens


def _structure_tokens(tokens: list[dict[str, Any]]) -> str:
    seen: set[str] = set()
    ordered: list[str] = []
    category_order = ("medicine", "manufacturer", "batch", "expiry")

    for category in category_order:
        category_tokens = [item for item in tokens if item["class"] == category]
        category_tokens.sort(key=lambda item: (item["top"], item["left"], -item["conf"]))
        for item in category_tokens:
            key = item["normalized"]
            if not key or key in seen:
                continue
            seen.add(key)
            ordered.append(item["raw"])
    return "\n".join(ordered).strip()


def ocr_core(image_input) -> tuple[str, float]:
    """OCR CONTRACT: Exactly 2 pytesseract calls per image.
    
    Call 1: pytesseract.image_to_string() → raw OCR text extraction
    Call 2: pytesseract.image_to_data() → per-word confidence data
    
    Returns: (raw_text: str, avg_confidence: float)
    No fallbacks. No multi-pass. Deterministic single-image processing.
    """
    _configure_tesseract()
    img_bgr = _load_image_bgr(image_input)
    normalized = preprocess_image(img_bgr)

    # ========================================================================
    # CALL 1: Extract raw OCR text
    # ========================================================================
    try:
        raw_text = pytesseract.image_to_string(
            normalized,
            config="--oem 3 --psm 6"
        )
    except pytesseract.TesseractNotFoundError:
        logger.error("Tesseract not found in PATH")
        raw_text = ""
    except Exception as exc:
        logger.warning(f"OCR text extraction error: {exc}")
        raw_text = ""

    # ========================================================================
    # CALL 2: Extract confidence data
    # ========================================================================
    try:
        data = pytesseract.image_to_data(
            normalized,
            config="--oem 3 --psm 6",
            output_type=pytesseract.Output.DICT,
        )
    except pytesseract.TesseractNotFoundError:
        logger.error("Tesseract not found in PATH")
        data = {}
    except Exception as exc:
        logger.warning(f"OCR confidence extraction error: {exc}")
        data = {}

    # Compute average confidence from per-word scores
    ocr_metrics, avg_confidence, _ = _ocr_metrics_from_data(data)
    
    # Store execution trace for debugging
    trace = {
        "ocr_calls": 2,
        "tesseract_calls": 2,
        "stage_1_used": True,
        "stage_2_used": True,
        "fallback_triggered": False,
        "raw_text": raw_text,
        "confidence": round(avg_confidence, 4),
        "contract_enforced": "2_calls_per_image",
    }
    ocr_core.last_trace = trace  # type: ignore[attr-defined]
    
    return raw_text, round(avg_confidence, 4)


ocr_core.last_trace = {
    "ocr_calls": 0,
    "fallback_triggered": True,
    "tesseract_calls": 0,
    "stage_1_used": False,
    "stage_2_used": False,
}  # type: ignore[attr-defined]


def preprocess_image(image_input) -> np.ndarray:
    """
    Prepare an image for optimal OCR performance.

    Pipeline:
        1. Load  Ã¢â€ â€™ handles file paths, PIL Images, and raw numpy arrays
        2. Resize Ã¢â€ â€™ standardise scale; Tesseract accuracy degrades on very
                    small or very large images.  224 Ãƒâ€” 224 is a safe middle
                    ground for label crops.
        3. Grayscale Ã¢â€ â€™ OCR engines work on intensity; colour channels add
                       noise without information gain.
        4. Gaussian blur Ã¢â€ â€™ softens salt-and-pepper noise from camera sensors
                           before thresholding, preventing speckle artefacts
                           from becoming fake ink dots.
        5. Adaptive threshold Ã¢â€ â€™ converts grey pixels to binary (black/white)
                                using a local neighbourhood mean rather than a
                                global cutoff, so uneven lighting (shadow on
                                packaging) doesn't obliterate text.
        6. Morphological dilation Ã¢â€ â€™ slightly thickens thin strokes that OCR
                                    engines can mistake for noise.

    Args:
        image_input: file path (str), PIL Image, or numpy ndarray.

    Returns:
        Preprocessed binary numpy array (uint8, 0 or 255).
    """
    # Ã¢â€â‚¬Ã¢â€â‚¬ Load Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    if isinstance(image_input, str):
        img = cv2.imread(image_input)
        if img is None:
            raise FileNotFoundError(f"Image not found: {image_input}")
    elif isinstance(image_input, Image.Image):
        img = cv2.cvtColor(np.array(image_input), cv2.COLOR_RGB2BGR)
    elif isinstance(image_input, np.ndarray):
        img = image_input.copy()
    else:
        raise TypeError(f"Unsupported image type: {type(image_input)}")

    # Ã¢â€â‚¬Ã¢â€â‚¬ Resize Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    # Upscale small images; downscale large ones.  Both extremes hurt OCR.
    target = 800  # use longer edge = 800 px; preserves aspect ratio better
    h, w = img.shape[:2]
    scale = target / max(h, w)
    if scale != 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)),
                         interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)

    # Ã¢â€â‚¬Ã¢â€â‚¬ Grayscale Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Ã¢â€â‚¬Ã¢â€â‚¬ Gaussian blur (noise reduction before threshold) Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)

    # Ã¢â€â‚¬Ã¢â€â‚¬ Adaptive threshold Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    binary = cv2.adaptiveThreshold(
        blurred,
        maxValue=255,
        adaptiveMethod=cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        thresholdType=cv2.THRESH_BINARY,
        blockSize=11,   # neighbourhood size (must be odd)
        C=2             # constant subtracted from the local mean
    )

    # Ã¢â€â‚¬Ã¢â€â‚¬ Light morphological dilation to strengthen thin strokes Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    kernel = np.ones((1, 1), np.uint8)
    processed = cv2.dilate(binary, kernel, iterations=1)

    return processed


# ---------------------------------------------------------------------------
# STAGE 1.5 Ã¢â‚¬â€ SMART REGION DETECTION & CROPPING
# ---------------------------------------------------------------------------

def detect_text_regions(binary_image: np.ndarray) -> list[dict[str, int]]:
    """
    Detect text-dense regions using contour analysis.
    
    Returns list of regions: [{'y_min', 'y_max', 'x_min', 'x_max', 'area', 'density'}]
    sorted top-to-bottom.
    """
    contours, _ = cv2.findContours(binary_image, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    regions = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        
        # Skip tiny noise regions
        if area < 200:
            continue
        
        # Estimate text density (non-zero pixels in bounding box)
        bbox = binary_image[y:y+h, x:x+w]
        density = np.count_nonzero(bbox) / max(area, 1)
        
        regions.append({
            'y_min': int(y),
            'y_max': int(y + h),
            'x_min': int(x),
            'x_max': int(x + w),
            'area': int(area),
            'density': float(density),
        })
    
    # Sort by y position (top to bottom)
    regions.sort(key=lambda r: r['y_min'])
    return regions


def crop_region_for_medicine_name(image_bgr: np.ndarray, binary: np.ndarray) -> np.ndarray | None:
    """
    Crop the TOP region (typically medicine name area).
    Use top 25% of image where dense text is found.
    """
    h, w = image_bgr.shape[:2]
    search_height = int(h * 0.3)
    
    top_section = binary[:search_height, :]
    regions = detect_text_regions(top_section)
    
    if not regions:
        return None
    
    # Use the highest-density text region in the top area
    best = max(regions, key=lambda r: r['density'])
    
    # Expand view slightly for context
    y_min = max(0, best['y_min'] - 10)
    y_max = min(h, best['y_max'] + 10)
    x_min = max(0, best['x_min'] - 5)
    x_max = min(w, best['x_max'] + 5)
    
    return image_bgr[y_min:y_max, x_min:x_max]


def crop_region_for_batch_expiry(image_bgr: np.ndarray, binary: np.ndarray) -> np.ndarray | None:
    """
    Crop the MIDDLE/BOTTOM region (typically batch, expiry, manufacturer).
    Use bottom 50% of image.
    """
    h, w = image_bgr.shape[:2]
    search_start = int(h * 0.4)
    
    bottom_section = binary[search_start:, :]
    regions = detect_text_regions(bottom_section)
    
    if not regions:
        return None
    
    # Take all regions in bottom half and combine their bounds
    if regions:
        y_positions = [r['y_min'] for r in regions] + [r['y_max'] for r in regions]
        x_positions = [r['x_min'] for r in regions] + [r['x_max'] for r in regions]
        
        y_min = max(0, min(y_positions) + search_start - 10)
        y_max = min(h, max(y_positions) + search_start + 10)
        x_min = max(0, min(x_positions) - 5)
        x_max = min(w, max(x_positions) + 5)
        
        return image_bgr[y_min:y_max, x_min:x_max]
    
    return None


def extract_text_from_region(region_bgr: np.ndarray, target_field: str = "general") -> str:
    """LEGACY - NOT USED IN RUNTIME. Returns no OCR output."""
    return ""

def extract_text(preprocessed_image: np.ndarray) -> str:
    """LEGACY - NOT USED IN RUNTIME. Returns no OCR output."""
    return ""

def extract_qr_data(image_input) -> str:
    """
    Decode QR content from the original image, if present.

    We intentionally use the unprocessed image here because aggressive OCR
    preprocessing can damage QR patterns.
    """
    try:
        img = _load_image_bgr(image_input)
        detector = cv2.QRCodeDetector()
        data, points, _ = detector.detectAndDecode(img)
        if data:
            return data.strip()
        return ""
    except Exception as exc:
        logger.debug(f"QR decode failed: {exc}")
        return ""


# ---------------------------------------------------------------------------
# STAGE 3 Ã¢â‚¬â€ Text Cleaning
# ---------------------------------------------------------------------------

# Common OCR substitution errors on medicine labels
_OCR_CORRECTIONS: dict[str, str] = {
    "0": "O",  # digit zero Ã¢â€ â€™ letter O  (in name context)
    "1": "I",  # digit one  Ã¢â€ â€™ letter I
    "|": "I",  # pipe       Ã¢â€ â€™ letter I
    "@": "A",
}

def clean_text(raw_text: str) -> str:
    """
    Normalise OCR output for reliable regex matching.

    Steps:
        1. Lowercase for case-insensitive matching
        2. Collapse multiple whitespace to single space
        3. Strip non-printable control characters
        4. Apply targeted OCR error corrections (within word context only)

    NOTE: We do NOT strip digits globally because batch numbers and dates
    require them.  Corrections are applied character-by-character only where
    context makes it safe (letters-only tokens).

    Returns:
        Cleaned string.
    """
    if not raw_text:
        return ""

    text = raw_text.lower()

    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)

    # Remove non-printable characters (keep newlines as spaces)
    text = re.sub(r"[^\x20-\x7E]", " ", text)

    # Normalise common symbol noise
    text = text.replace("Ã‚Â°", "").replace("Ã‚Â®", "").replace("Ã¢â€žÂ¢", "")

    # Fix pipe character used as I
    text = text.replace("|", "i")

    return text.strip()


def _ocr_text_score(text: str) -> float:
    """
    Score OCR output so the pipeline can prefer the most useful text.

    The heuristic favors alphanumeric density, medicine-related keywords,
    and a reasonable line structure.
    """
    if not text:
        return 0.0

    lower = text.lower()
    alnum_chars = sum(c.isalnum() for c in text)
    density = alnum_chars / max(len(text), 1)
    line_count = len([line for line in text.splitlines() if line.strip()])
    keyword_hits = sum(
        1
        for kw in ("batch", "lot", "exp", "expiry", "mfg", "manufact", "mrp")
        if kw in lower
    )
    digit_bonus = 1.0 if re.search(r"\d", text) else 0.0
    return (
        0.45 * density
        + 0.20 * min(line_count / 8.0, 1.0)
        + 0.25 * (keyword_hits / 6.0)
        + 0.10 * digit_bonus
    )


# ---------------------------------------------------------------------------
# STAGE 4 Ã¢â‚¬â€ Field Extraction
# ---------------------------------------------------------------------------

# Ã¢â€â‚¬Ã¢â€â‚¬ Compiled regex patterns Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

# Batch: B followed by alphanumeric, or LOT/BATCH prefix
_RE_BATCH = re.compile(
    r"\b(?:batch\s*no\.?\s*[:\-]?\s*|lot\s*no\.?\s*[:\-]?\s*|b/n\s*[:\-]?\s*)?"
    r"([a-z]{0,3}\d{3,}[a-z0-9]*)\b",
    re.IGNORECASE
)

# Expiry: EXP / EXPIRY / USE BY + date
_RE_EXPIRY = re.compile(
    r"(?:exp(?:iry|\.)?|use\s*by|expiry\s*date)[:\s\-]*"
    r"(\d{1,2}[\/\-]\d{4}|\d{1,2}[\/\-]\d{2})\b",
    re.IGNORECASE
)

# Expiry date standalone (fallback): MM/YYYY or MM-YYYY
_RE_DATE_STANDALONE = re.compile(
    r"\b(\d{2})[\/\-](\d{4})\b"
)

# MFG date
_RE_MFG = re.compile(
    r"(?:mfg(?:\s*date)?|mfd|manufactured\s*on|manufacture\s*date)[:\s\-]*"
    r"(\d{1,2}[\/\-]\d{4}|\d{1,2}[\/\-]\d{2})\b",
    re.IGNORECASE
)

# Manufacturer: company suffixes
_RE_MANUFACTURER = re.compile(
    r"([A-Za-z][A-Za-z\s&']{2,40}"
    r"(?:ltd|limited|pharma|pharmaceuticals?|labs?|laboratories|company|corp|inc|pvt|healthcare)\.?)",
    re.IGNORECASE
)

# Medicine name heuristic: longest capitalised token cluster
_RE_NAME_CANDIDATES = re.compile(
    r"\b([A-Z][a-zA-Z\-]{3,}(?:\s+[A-Z][a-zA-Z]{2,}){0,3})\b"
)

_MEDICINE_HINTS = (
    "tablet",
    "capsule",
    "syrup",
    "injection",
    "ointment",
    "cream",
    "suspension",
    "solution",
    "mg",
    "ml",
)

_GENERIC_OCR_STOPWORDS = {
    "about",
    "and",
    "care",
    "contact",
    "cookie",
    "cookies",
    "download",
    "exporter",
    "guide",
    "home",
    "info",
    "legal",
    "more",
    "notice",
    "policy",
    "privacy",
    "product",
    "products",
    "read",
    "report",
    "site",
    "support",
    "terms",
    "test",
    "use",
    "view",
    "whatsapp",
}


def _best_batch(text: str) -> str:
    """Extract the most likely batch number from text."""
    matches = _RE_BATCH.findall(text)
    if not matches:
        return ""
    # Prefer longer matches (more specific)
    return max(matches, key=len).upper()


def _best_date(pattern: re.Pattern, text: str) -> str:
    """Extract first date match for a given labelled pattern."""
    m = pattern.search(text)
    if m:
        return _normalize_date_token(m.group(1))
    return ""


def _normalize_date_token(token: str) -> str:
    """
    Normalize OCR date fragments into a consistent DD/MM/YYYY or MM/YYYY form.
    """
    token = token.strip()
    if re.fullmatch(r"\d{4}[-/]\d{1,2}", token):
        year, month = re.split(r"[-/]", token)
        return f"{year}-{month.zfill(2)}"
    token = token.replace(".", "/").replace("-", "/")
    token = re.sub(r"\s+", "", token)

    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})", token)
    if m:
        day = m.group(1).zfill(2)
        month = m.group(2).zfill(2)
        year = m.group(3)
        return f"{day}/{month}/{year}"

    m = re.fullmatch(r"(\d{1,2})/(\d{2}|\d{4})", token)
    if not m:
        m = re.fullmatch(r"(\d{4})/(\d{1,2})", token)
        if m:
            return f"{m.group(1)}-{m.group(2).zfill(2)}"
        return token

    month = m.group(1).zfill(2)
    year = m.group(2)
    return f"{month}/{year}"


def _parse_strict_date(token: str) -> date | None:
    """Parse DD/MM/YYYY, DD/MM/YY, MM/YYYY, MM/YY, or YYYY-MM into a date."""
    token = _normalize_date_token(token)
    m = re.fullmatch(r"(\d{4})-(\d{1,2})", token)
    if m:
        year = int(m.group(1))
        month = int(m.group(2))
        if not 1 <= month <= 12:
            return None
        try:
            return date(year, month, 1)
        except ValueError:
            return None

    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})", token)
    if m:
        day = int(m.group(1))
        month = int(m.group(2))
        year = int(m.group(3))
        if len(m.group(3)) == 2:
            year += 2000
        try:
            return date(year, month, day)
        except ValueError:
            return None

    m = re.fullmatch(r"(\d{1,2})/(\d{2}|\d{4})", token)
    if not m:
        return None

    month = int(m.group(1))
    year = int(m.group(2))
    if len(m.group(2)) == 2:
        year += 2000
    if not 1 <= month <= 12:
        return None
    try:
        return date(year, month, 1)
    except ValueError:
        return None


def _is_valid_batch_value(value: str) -> bool:
    value = (value or "").strip().upper()
    if not value:
        return False
    if len(value) < 3 or len(value) > 24:
        return False
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9\-\/\.]*", value):
        return False
    if not re.search(r"[A-Z]", value) or not re.search(r"\d", value):
        return False
    if re.fullmatch(r"\d{4}", value):
        return False
    if any(hint in value.lower() for hint in ("batch", "lot", "expiry", "exp", "mfg", "manufact", "date")):
        return False
    return True


def _is_valid_manufacturer_value(value: str) -> bool:
    value = (value or "").strip()
    if not value:
        return False
    lower = value.lower()
    if any(hint in lower for hint in ("batch", "expiry", "exp ", "mfg", "mfd")):
        return False
    if any(hint in lower for hint in ("tablet", "capsule", "syrup", "injection", "medicine", "vitamin")):
        return False
    if re.search(r"\b\d{1,2}[/-]\d{2,4}\b", value):
        return False
    if not re.search(r"\b(ltd|limited|pharma|pharmaceuticals?|labs?|laboratories|company|corp|inc|pvt|healthcare|care)\.?\b\s*$", lower):
        return False
    return True


def _line_bucket(index: int, total: int) -> str:
    if total <= 0:
        return "middle"
    ratio = index / max(total - 1, 1)
    if ratio <= 0.33:
        return "top"
    if ratio >= 0.67:
        return "bottom"
    return "middle"


def _region_origin_label(bucket: str) -> str:
    if bucket in {"top", "middle", "bottom"}:
        return bucket
    return "full"


def _line_alignment_score(field_name: str, bucket: str, line_index: int, total_lines: int) -> float:
    total_lines = max(total_lines, 1)
    position = line_index / max(total_lines - 1, 1)
    if field_name == "medicine_name":
        return round(max(0.0, 1.0 - position), 4)
    if field_name == "manufacturer":
        return round(max(0.0, 1.0 - abs(position - 0.25) * 2.0), 4)
    if field_name == "batch_number":
        return round(max(0.0, 1.0 - abs(position - 0.55) * 2.0), 4)
    if field_name in {"expiry_date", "mfg_date"}:
        return round(max(0.0, 1.0 - abs(position - 0.8) * 2.0), 4)
    return 0.0


def _region_alignment_score(field_name: str, bucket: str, line_text: str = "") -> float:
    text = (line_text or "").lower()
    origin = (bucket or "full").lower()
    score = 0.0
    if field_name == "medicine_name":
        score += {"top": 0.35, "middle": 0.18, "bottom": 0.05, "full": 0.15}.get(origin, 0.1)
    elif field_name == "manufacturer":
        score += {"top": 0.22, "middle": 0.28, "bottom": 0.08, "full": 0.12}.get(origin, 0.1)
    elif field_name == "batch_number":
        score += {"top": 0.05, "middle": 0.24, "bottom": 0.28, "full": 0.12}.get(origin, 0.1)
    elif field_name in {"expiry_date", "mfg_date"}:
        score += {"top": 0.03, "middle": 0.18, "bottom": 0.30, "full": 0.12}.get(origin, 0.1)
    if field_name == "expiry_date" and any(hint in text for hint in ("exp", "expiry", "best before", "use by", "use before")):
        score += 0.12
    if field_name == "mfg_date" and any(hint in text for hint in ("mfg", "mfd", "manufactured", "manufacture", "manuf date")):
        score += 0.12
    if field_name == "batch_number" and any(hint in text for hint in ("batch", "lot", "b no")):
        score += 0.12
    if field_name == "manufacturer" and any(hint in text for hint in ("ltd", "limited", "pharma", "labs", "industries", "care", "med")):
        score += 0.12
    return round(min(score, 0.45), 4)


def _keyword_proximity_score(field_name: str, line_text: str = "", token: str = "") -> float:
    text = f"{token} {line_text}".lower()
    if field_name == "expiry_date":
        if any(hint in text for hint in ("exp", "expiry", "best before", "use by", "use before")):
            return 0.35
    elif field_name == "mfg_date":
        if any(hint in text for hint in ("mfg", "mfd", "manufactured", "manufacture", "manuf date")):
            return 0.35
    elif field_name == "batch_number":
        if any(hint in text for hint in ("batch", "lot", "b no", "batch no", "lot no")):
            return 0.25
    elif field_name == "manufacturer":
        if any(hint in text for hint in ("ltd", "limited", "pharma", "labs", "industries", "care", "med")):
            return 0.25
    return 0.0


def _structure_confidence_score(
    field_name: str,
    bucket: str,
    line_index: int,
    total_lines: int,
    line_text: str = "",
    token: str = "",
) -> dict[str, float]:
    line_alignment = _line_alignment_score(field_name, bucket, line_index, total_lines)
    region_alignment = _region_alignment_score(field_name, bucket, line_text)
    keyword_proximity = _keyword_proximity_score(field_name, line_text, token)
    structure_score = round(line_alignment + region_alignment + keyword_proximity, 4)
    return {
        "line_alignment_score": round(line_alignment, 4),
        "region_alignment_score": round(region_alignment, 4),
        "keyword_proximity_score": round(keyword_proximity, 4),
        "structure_score": structure_score,
    }


def _token_format_weight(field_name: str, token: str) -> float:
    text = (token or "").strip()
    lower = text.lower()
    if not text:
        return 0.0

    if field_name == "batch_number":
        if _RE_BATCH_STRICT.search(text):
            return 0.95
        if re.fullmatch(r"[A-Z0-9][A-Z0-9\-\/\.]{2,23}", text.upper()) and re.search(r"\d", text):
            return 0.75
        return 0.0

    if field_name in {"expiry_date", "mfg_date"}:
        if re.fullmatch(r"\d{1,2}[/-]\d{2,4}", text):
            return 0.9
        if re.fullmatch(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", text):
            return 0.92
        if field_name == "expiry_date" and _RE_EXPIRY_STRICT.search(text):
            return 0.95
        if field_name == "mfg_date" and _RE_MFG_STRICT.search(text):
            return 0.95
        return 0.0

    if field_name == "manufacturer":
        if _RE_MANUFACTURER_STRICT.search(text):
            return 0.92
        if _RE_MANUFACTURER.search(text):
            return 0.85
        if any(suffix in lower for suffix in ("ltd", "limited", "pharma", "labs", "healthcare", "corp", "inc", "pvt")):
            return 0.8
        return 0.0

    if field_name == "medicine_name":
        if _RE_NAME_CANDIDATES.search(text):
            return 0.9
        if text.isupper() and len(text) >= 4 and not re.search(r"\d{3,}", text):
            return 0.75
        if text.istitle() and len(text.split()) <= 4:
            return 0.7
        return 0.0

    return 0.0


def _token_position_weight(field_name: str, bucket: str) -> float:
    if field_name == "medicine_name":
        return {"top": 0.35, "middle": 0.15, "bottom": 0.05}.get(bucket, 0.1)
    if field_name == "manufacturer":
        return {"top": 0.15, "middle": 0.35, "bottom": 0.25}.get(bucket, 0.1)
    if field_name in {"batch_number", "expiry_date", "mfg_date"}:
        return {"top": 0.05, "middle": 0.15, "bottom": 0.35}.get(bucket, 0.1)
    return 0.0


def _token_spatial_score(field_name: str, bucket: str, token: str, line_text: str = "") -> float:
    bucket = bucket or "middle"
    text = f"{token} {line_text}".lower()
    score = 0.0

    if field_name == "batch_number":
        score += {"top": 0.02, "middle": 0.10, "bottom": 0.16}.get(bucket, 0.05)
        if any(hint in text for hint in ("batch", "lot", "b.no", "batch no", "lot no")):
            score += 0.08
    elif field_name == "expiry_date":
        score += {"top": 0.02, "middle": 0.08, "bottom": 0.20}.get(bucket, 0.05)
        if any(hint in text for hint in ("exp", "expiry", "best before", "use by", "use before")):
            score += 0.10
    elif field_name == "mfg_date":
        score += {"top": 0.02, "middle": 0.08, "bottom": 0.18}.get(bucket, 0.05)
        if any(hint in text for hint in ("mfg", "mfd", "manufactured", "manufacture")):
            score += 0.10
    elif field_name == "manufacturer":
        score += {"top": 0.12, "middle": 0.16, "bottom": 0.06}.get(bucket, 0.05)
        if any(hint in text for hint in ("ltd", "limited", "pharma", "labs", "healthcare", "company", "corp", "inc", "pvt")):
            score += 0.08
    elif field_name == "medicine_name":
        score += {"top": 0.18, "middle": 0.08, "bottom": 0.03}.get(bucket, 0.05)
    return round(min(score, 0.28), 4)


def _token_length_validity_weight(field_name: str, token: str) -> float:
    text = (token or "").strip()
    if not text:
        return 0.0
    length = len(text)
    if field_name == "medicine_name":
        if 4 <= length <= 24:
            return 0.15
        return 0.0
    if field_name == "manufacturer":
        if 6 <= length <= 48:
            return 0.15
        return 0.0
    if field_name == "batch_number":
        if 3 <= length <= 24:
            return 0.15
        return 0.0
    if field_name in {"expiry_date", "mfg_date"}:
        if 5 <= length <= 10:
            return 0.15
        return 0.0
    return 0.0


def _token_symbol_penalty(token: str) -> float:
    text = (token or "").strip()
    if not text:
        return 1.0
    bad_chars = sum(1 for ch in text if not (ch.isalnum() or ch in "/-_."))
    return min(bad_chars / max(len(text), 1), 0.4)


def _token_digit_presence_score(token: str) -> float:
    text = (token or "").strip()
    digits = sum(ch.isdigit() for ch in text)
    return min(digits / 4.0, 0.25)


def _token_keyword_proximity_score(token: str, field_name: str, line_text: str = "") -> float:
    text = f"{token} {line_text}".lower()
    if field_name == "expiry_date":
        keywords = ("exp", "expiry", "best before", "use by", "use before")
    elif field_name == "mfg_date":
        keywords = ("mfg", "mfd", "manufactured", "manufacture", "date")
    else:
        keywords = ()
    if any(keyword in text for keyword in keywords):
        return 0.25
    return 0.0


_MEDICINE_NAME_STOPWORDS = {
    "keep",
    "safe",
    "please",
    "read",
    "storage",
    "store",
    "instructions",
    "information",
    "connection",
    "medicine",
    "tablets",
    "tablet",
    "capsule",
    "capsules",
    "dose",
    "use",
    "warning",
    "contents",
    "content",
    "package",
    "packaging",
}


def _medicine_name_quality_score(token: str, line_text: str = "") -> float:
    text = (token or "").strip()
    if not text:
        return 0.0

    lower = text.lower()
    if re.search(r"\d", text):
        return -0.25
    if any(hint in lower for hint in ("batch", "exp", "expiry", "mfg", "manufact")):
        return -0.35
    if lower in _MEDICINE_NAME_STOPWORDS:
        return -0.30

    score = 0.0
    if 4 <= len(text) <= 24 and text.isalpha():
        score += 0.18
    if text.istitle():
        score += 0.12
    if re.fullmatch(r"[A-Z][A-Za-z&'\- ]{2,32}", text):
        score += 0.10
    if any(hint in line_text.lower() for hint in ("medicine", "tablet", "capsule", "drug", "brand")):
        score += 0.05
    return round(max(-0.4, min(0.25, score)), 4)


def _date_acceptance_score(token: str, field_name: str, line_text: str = "") -> float:
    text = (token or "").strip()
    if not text:
        return 0.0
    normalized = _normalize_for_field(field_name, text)
    base = 0.0
    if re.fullmatch(r"\d{1,2}[/-]\d{2,4}", normalized):
        base = 0.60
    elif re.fullmatch(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", normalized):
        base = 0.68
    elif re.search(r"\d{2}[/-]\d{4}", normalized):
        base = 0.52
    elif re.search(r"\d{4}", normalized):
        base = 0.35

    if field_name == "expiry_date":
        if _RE_EXPIRY_STRICT.search(text):
            base += 0.18
        if _RE_DATE_STANDALONE.search(text):
            base += 0.10
    if field_name == "mfg_date" and _RE_MFG_STRICT.search(text):
        base += 0.18

    digit_bonus = _token_digit_presence_score(text)
    proximity_bonus = _token_keyword_proximity_score(text, field_name, line_text)
    partial_bonus = 0.0
    if re.search(r"\d{1,2}[/-]\d{2,4}", text) and not re.fullmatch(r"\d{1,2}[/-]\d{2,4}", text):
        partial_bonus = 0.10
    if field_name == "expiry_date" and re.search(r"exp", text.lower()) and re.search(r"\d", text):
        partial_bonus = max(partial_bonus, 0.12)

    return round(min(1.0, base + digit_bonus + proximity_bonus + partial_bonus), 4)


def _merge_date_fragments(line: str, field_name: str) -> list[str]:
    text = (line or "").strip()
    if not text:
        return []

    compact = re.sub(r"\s+", "", text)
    normalized = re.sub(r"\s+", " ", text.lower())
    candidates: list[str] = []

    keyword_prefixes = {
        "expiry_date": ("exp", "expiry", "bestbefore", "useby", "usebefore"),
        "mfg_date": ("mfg", "mfd", "manufactured", "manufacture"),
    }.get(field_name, ())

    if keyword_prefixes:
        for prefix in keyword_prefixes:
            if prefix in normalized:
                after = normalized.split(prefix, 1)[1]
                after = after.replace(":", " ").replace("-", " ").replace("/", " ")
                for match in re.findall(r"\b\d{1,2}(?:\s*[/-]\s*\d{2,4}|\s+\d{2,4}|\s+\d{1,2}\s*[/-]\s*\d{2,4})\b", after):
                    candidate = re.sub(r"\s*([/-])\s*", r"\1", match)
                    candidates.append(candidate)
                for match in re.findall(r"\b\d{4}\b", after):
                    candidates.append(match)

    for match in re.findall(r"\b\d{1,2}\s*[/-]\s*\d{2,4}\b", text):
        candidates.append(re.sub(r"\s*([/-])\s*", r"\1", match))
    for match in re.findall(r"\b\d{1,2}\s+\d{2,4}\b", text):
        parts = match.split()
        candidates.append(f"{parts[0]}/{parts[1]}")
    if field_name == "expiry_date":
        for match in re.findall(r"\b\d{2}\s*\d{4}\b", compact):
            if len(match) == 6:
                candidates.append(f"{match[:2]}/{match[2:]}")
        for match in re.findall(r"\b\d{4}\s*[/-]\s*\d{1,2}\b", text):
            normalized_match = re.sub(r"\s*([/-])\s*", r"\1", match)
            candidates.append(normalized_match.replace("/", "-"))
    if field_name == "mfg_date":
        for match in re.findall(r"\b\d{4}\b", text):
            candidates.append(match)

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized_candidate = _normalize_for_field(field_name, candidate)
        if not normalized_candidate or normalized_candidate in seen:
            continue
        seen.add(normalized_candidate)
        deduped.append(normalized_candidate)
    return deduped


def _line_structured_candidates(line: str, field_name: str, bucket: str, line_index: int) -> list[dict[str, Any]]:
    text = (line or "").strip()
    if not text:
        return []

    tokens = [match.group(0) for match in re.finditer(r"[A-Za-z0-9][A-Za-z0-9\-/\.]*", text)]
    line_text = " ".join(tokens).strip()
    candidates: list[dict[str, Any]] = []

    if field_name in {"expiry_date", "mfg_date"}:
        for candidate in _merge_date_fragments(text, field_name):
            date_score = _date_acceptance_score(candidate, field_name, line_text)
            if date_score < 0.45:
                continue
            spatial_score = _token_spatial_score(field_name, bucket, candidate, line_text)
            candidates.append(
                {
                    "token": candidate,
                    "normalized": _normalize_ocr_token(candidate),
                    "lexical_score": round(date_score, 4),
                    "spatial_score": spatial_score,
                    "score": round(min(1.0, date_score + spatial_score), 4),
                    "line_index": line_index,
                    "line_bucket": bucket,
                    "region_origin": _region_origin_label(bucket),
                    "line_text": line_text,
                    "source": "line",
                }
            )
    elif field_name == "batch_number":
        for match in re.finditer(r"\b(?:batch|batch\s*no\.?|b\.?no\.?|lot|lot\s*no\.?)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-\/]{2,})\b", text, re.IGNORECASE):
            candidate = (match.group(1) or "").strip()
            normalized = _normalize_ocr_token(candidate)
            if not normalized or not _is_valid_batch_value(normalized):
                continue
            lexical_score = 0.95
            spatial_score = _token_spatial_score(field_name, bucket, candidate, line_text)
            candidates.append(
                {
                    "token": candidate,
                    "normalized": normalized,
                    "lexical_score": lexical_score,
                    "spatial_score": spatial_score,
                    "score": round(min(1.0, lexical_score + spatial_score), 4),
                    "line_index": line_index,
                    "line_bucket": bucket,
                    "region_origin": _region_origin_label(bucket),
                    "line_text": line_text,
                    "source": "line",
                }
            )
    elif field_name == "manufacturer":
        cleaned = re.sub(r"^(?:manufacturer|mfr|by)\s*[:\-]?\s*", "", text, flags=re.IGNORECASE).strip()
        if cleaned and _is_valid_manufacturer_value(cleaned):
            lexical_score = 0.88 if any(hint in cleaned.lower() for hint in ("ltd", "limited", "pharma", "labs", "healthcare", "company", "corp", "inc", "pvt")) else 0.72
            spatial_score = _token_spatial_score(field_name, bucket, cleaned, line_text)
            candidates.append(
                {
                    "token": cleaned,
                    "normalized": _normalize_ocr_token(cleaned),
                    "lexical_score": lexical_score,
                    "spatial_score": spatial_score,
                    "score": round(min(1.0, lexical_score + spatial_score), 4),
                    "line_index": line_index,
                    "line_bucket": bucket,
                    "region_origin": _region_origin_label(bucket),
                    "line_text": line_text,
                    "source": "line",
                }
            )

    return candidates


def _cross_line_structured_candidates(
    lines: list[str],
    field_name: str,
    line_index: int,
    bucket: str,
    total_lines: int,
) -> list[dict[str, Any]]:
    if field_name not in {"expiry_date", "mfg_date"} or not lines:
        return []

    current = lines[line_index] if 0 <= line_index < len(lines) else ""
    previous = lines[line_index - 1] if line_index - 1 >= 0 else ""
    following = lines[line_index + 1] if line_index + 1 < len(lines) else ""
    windows = [current]
    if previous:
        windows.append(f"{previous} {current}")
    if following:
        windows.append(f"{current} {following}")

    candidates: list[dict[str, Any]] = []
    for window in windows:
        window_tokens = [match.group(0) for match in re.finditer(r"[A-Za-z0-9][A-Za-z0-9\-/\.]*", window)]
        window_text = " ".join(window_tokens).strip()
        for candidate in _merge_date_fragments(window, field_name):
            date_score = _date_acceptance_score(candidate, field_name, window_text)
            if date_score < 0.45:
                continue
            structure = _structure_confidence_score(field_name, bucket, line_index, total_lines, window_text, candidate)
            spatial_score = _token_spatial_score(field_name, bucket, candidate, window_text)
            candidates.append(
                {
                    "token": candidate,
                    "normalized": _normalize_ocr_token(candidate),
                    "lexical_score": round(date_score, 4),
                    "spatial_score": spatial_score,
                    "structure_score": structure["structure_score"],
                    "line_alignment_score": structure["line_alignment_score"],
                    "region_alignment_score": structure["region_alignment_score"],
                    "keyword_proximity_score": structure["keyword_proximity_score"],
                    "score": round(min(1.0, date_score + spatial_score + structure["structure_score"] * 0.1), 4),
                    "line_index": line_index,
                    "line_bucket": bucket,
                    "region_origin": _region_origin_label(bucket),
                    "line_text": window_text,
                    "source": "cross_line",
                }
            )
    return candidates


def _build_token_pools(raw_text: str) -> dict[str, list[dict[str, Any]]]:
    lines = [line.strip() for line in (raw_text or "").splitlines() if line.strip()]
    total_lines = len(lines)
    pools: dict[str, list[dict[str, Any]]] = {name: [] for name in CORE_FIELD_NAMES}
    pools["noise"] = []

    for line_index, line in enumerate(lines):
        bucket = _line_bucket(line_index, total_lines)
        tokens = [match.group(0) for match in re.finditer(r"[A-Za-z0-9][A-Za-z0-9\-/\.]*", line)]
        line_text = " ".join(tokens).strip()
        for field_name in {"expiry_date", "mfg_date"}:
            for candidate in _line_structured_candidates(line, field_name, bucket, line_index):
                pools[field_name].append(candidate)
            for candidate in _cross_line_structured_candidates(lines, field_name, line_index, bucket, total_lines):
                pools[field_name].append(candidate)
            for candidate in _merge_date_fragments(line, field_name):
                date_score = _date_acceptance_score(candidate, field_name, line_text)
                if date_score >= 0.45:
                    structure = _structure_confidence_score(field_name, bucket, line_index, total_lines, line_text, candidate)
                    spatial_score = _token_spatial_score(field_name, bucket, candidate, line_text)
                    pools[field_name].append(
                        {
                            "token": candidate,
                            "normalized": _normalize_ocr_token(candidate),
                            "lexical_score": round(date_score, 4),
                            "spatial_score": spatial_score,
                            "structure_score": structure["structure_score"],
                            "line_alignment_score": structure["line_alignment_score"],
                            "region_alignment_score": structure["region_alignment_score"],
                            "keyword_proximity_score": structure["keyword_proximity_score"],
                            "score": round(min(1.0, date_score + spatial_score + structure["structure_score"] * 0.1), 4),
                            "line_index": line_index,
                            "line_bucket": bucket,
                            "region_origin": _region_origin_label(bucket),
                            "line_text": line_text,
                            "source": "token",
                        }
                    )
        for candidate in _line_structured_candidates(line, "batch_number", bucket, line_index):
            pools["batch_number"].append(candidate)
        for candidate in _line_structured_candidates(line, "manufacturer", bucket, line_index):
            pools["manufacturer"].append(candidate)
        for token in tokens:
            normalized = _normalize_ocr_token(token)
            if not normalized:
                continue
            classes = []
            token_date_fields: set[str] = set()
            for field_name in CORE_FIELD_NAMES:
                format_weight = _token_format_weight(field_name, token)
                if format_weight <= 0:
                    if field_name in {"expiry_date", "mfg_date"}:
                        date_score = _date_acceptance_score(token, field_name, line_text)
                        if date_score >= 0.45:
                            token_date_fields.add(field_name)
                    continue
                position_weight = _token_position_weight(field_name, bucket)
                length_weight = _token_length_validity_weight(field_name, token)
                symbol_penalty = _token_symbol_penalty(token)
                spatial_score = _token_spatial_score(field_name, bucket, token, line_text)
                structure = _structure_confidence_score(field_name, bucket, line_index, total_lines, line_text, token)
                lexical_score = max(
                    0.0,
                    format_weight + length_weight - symbol_penalty,
                )
                if field_name == "medicine_name":
                    lexical_score = max(0.0, lexical_score + _medicine_name_quality_score(token, line_text))
                score = round(
                    max(
                        0.0,
                        lexical_score + position_weight + spatial_score + structure["structure_score"] * 0.1,
                    ),
                    4,
                )
                if score <= 0.0:
                    continue
                pools[field_name].append(
                    {
                        "token": token,
                        "normalized": normalized,
                        "lexical_score": round(lexical_score, 4),
                        "spatial_score": spatial_score,
                        "structure_score": structure["structure_score"],
                        "line_alignment_score": structure["line_alignment_score"],
                        "region_alignment_score": structure["region_alignment_score"],
                        "keyword_proximity_score": structure["keyword_proximity_score"],
                        "score": score,
                        "line_index": line_index,
                        "line_bucket": bucket,
                        "region_origin": _region_origin_label(bucket),
                        "line_text": line_text,
                        "source": "token",
                    }
                )
                classes.append(field_name)
            for field_name in token_date_fields:
                date_score = _date_acceptance_score(token, field_name, line_text)
                if date_score >= 0.45:
                    spatial_score = _token_spatial_score(field_name, bucket, token, line_text)
                    structure = _structure_confidence_score(field_name, bucket, line_index, total_lines, line_text, token)
                    pools[field_name].append(
                        {
                            "token": token,
                            "normalized": normalized,
                            "lexical_score": round(date_score, 4),
                            "spatial_score": spatial_score,
                            "structure_score": structure["structure_score"],
                            "line_alignment_score": structure["line_alignment_score"],
                            "region_alignment_score": structure["region_alignment_score"],
                            "keyword_proximity_score": structure["keyword_proximity_score"],
                            "score": round(min(1.0, date_score + spatial_score + structure["structure_score"] * 0.1), 4),
                            "line_index": line_index,
                            "line_bucket": bucket,
                            "region_origin": _region_origin_label(bucket),
                            "line_text": line_text,
                            "source": "token",
                        }
                    )
            if not classes:
                pools["noise"].append(
                    {
                        "token": token,
                        "normalized": normalized,
                        "score": max(0.0, 0.1 - _token_symbol_penalty(token)),
                        "line_index": line_index,
                        "line_bucket": bucket,
                        "region_origin": _region_origin_label(bucket),
                        "source": "token",
                        "structure_score": 0.0,
                        "line_alignment_score": 0.0,
                        "region_alignment_score": 0.0,
                        "keyword_proximity_score": 0.0,
                        "spatial_score": 0.0,
                        "lexical_score": 0.0,
                    }
                )

    return pools


def _candidate_evidence_reason(
    candidates: list[dict[str, Any]],
    field_name: str,
    raw_text: str,
) -> str:
    text = (raw_text or "").strip()
    if not text:
        return "NO_TEXT_DETECTED"
    if not candidates:
        return "NO_VALID_CANDIDATES"

    normalized_values = {
        _normalize_for_field(field_name, str(item.get("token", "")))
        for item in candidates
        if _normalize_for_field(field_name, str(item.get("token", "")))
    }
    if len(normalized_values) > 1:
        return "CONFLICTING_CANDIDATES"

    if _ocr_text_structure_score(text) < 0.35:
        return "LOW_OCR_CONFIDENCE"

    return "OVER_STRICT_VALIDATION"


def _apply_evidence_reweighting(
    candidates: list[dict[str, Any]],
    field_name: str,
    raw_text: str,
) -> list[dict[str, Any]]:
    if not candidates:
        return candidates

    reason = _candidate_evidence_reason(candidates, field_name, raw_text)
    threshold = _field_threshold(field_name)
    borderline_window = 0.12 if field_name in {"expiry_date", "mfg_date"} else 0.08

    adjusted: list[dict[str, Any]] = []
    for item in candidates:
        score = float(item.get("score", 0.0))
        token = str(item.get("token", ""))
        line_text = str(item.get("line_text", ""))

        if reason == "LOW_OCR_CONFIDENCE":
            score *= 0.92
        elif reason == "CONFLICTING_CANDIDATES":
            score *= 0.95
        elif reason == "OVER_STRICT_VALIDATION":
            if score >= threshold - borderline_window:
                score += 0.08
            elif field_name in {"expiry_date", "mfg_date"} and _date_acceptance_score(token, field_name, line_text) >= 0.45:
                score += 0.06
            elif field_name == "manufacturer" and _is_valid_manufacturer_value(token):
                score += 0.04
            elif field_name == "medicine_name" and not any(
                hint in token.lower() for hint in ("batch", "exp", "mfg", "manufact", "tablet", "capsule")
            ):
                score += 0.03

        adjusted.append({**item, "score": round(max(0.0, score), 4)})

    return adjusted


def _select_token_candidate(candidates: list[dict[str, Any]], field_name: str, raw_text: str = "") -> tuple[str, float]:
    if not candidates:
        return "", 0.0

    threshold = _field_threshold(field_name)

    def _pick(pool: list[dict[str, Any]]) -> dict[str, Any]:
        return max(
            pool,
            key=lambda item: (
                float(item.get("score", 0.0)) + 0.12 * float(item.get("structure_score", 0.0)),
                float(item.get("structure_score", 0.0)),
                -int(item.get("line_index", 0) or 0),
                len(str(item.get("token", ""))),
            ),
        )

    winner = _pick(candidates)
    if winner["score"] < threshold:
        adjusted_candidates = _apply_evidence_reweighting(candidates, field_name, raw_text)
        adjusted_winner = _pick(adjusted_candidates)
        if adjusted_winner["score"] > winner["score"]:
            winner = adjusted_winner

    if winner["score"] < threshold:
        return "", round(winner["score"], 4)
    if field_name == "batch_number" and not _is_valid_batch_value(winner["token"]):
        return "", round(winner["score"], 4)
    if field_name in {"expiry_date", "mfg_date"} and not _parse_strict_date(_normalize_date_token(winner["token"])):
        return "", round(winner["score"], 4)
    if field_name == "manufacturer" and not _is_valid_manufacturer_value(winner["token"]):
        return "", round(winner["score"], 4)
    if field_name == "medicine_name" and any(hint in winner["token"].lower() for hint in ("batch", "exp", "mfg", "manufact", "tablet", "capsule")):
        return "", round(winner["score"], 4)
    return winner["token"], round(winner["score"], 4)


def _date_confidence_gate(value: str, anchor_hit: bool, ocr_score: float) -> tuple[bool, float, str]:
    """Return (is_valid, confidence, reason)."""
    normalized = _normalize_date_token(value)
    parsed = _parse_strict_date(normalized)
    if not parsed:
        return False, 0.0, "INVALID_FORMAT"
    if parsed.year < 2000 or parsed.year > 2100:
        return False, 0.0, "INVALID_FORMAT"
    anchor_score = 0.4 if anchor_hit else 0.0
    clarity_score = 0.3 * _clamp(ocr_score)
    token_score = 0.3 if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", normalized) or re.fullmatch(r"\d{1,2}/\d{2,4}", normalized) else 0.0
    confidence = round(_clamp(anchor_score + clarity_score + token_score), 4)
    if confidence < 0.65:
        return False, confidence, "LOW_CONFIDENCE"
    return True, confidence, ""



def _best_manufacturer(text: str) -> str:
    matches = _RE_MANUFACTURER.findall(text)
    if not matches:
        return ""
    # Return the longest match; likely the full company name
    return max(matches, key=len).strip().title()


def _best_label_line(raw_text: str) -> str:
    """
    Pick the line most likely to contain the medicine name.

    We prefer title-like lines near the top of the label while ignoring lines
    that mostly contain batch, date, or manufacturer information.
    """
    lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
    if not lines:
        return ""

    scored_lines: list[tuple[float, str]] = []
    for idx, line in enumerate(lines[:8]):
        lower = line.lower()
        if any(
            hint in lower
            for hint in ("batch", "lot", "exp", "expiry", "mfg", "manufact", "mrp")
        ):
            continue

        alpha_ratio = sum(c.isalpha() for c in line) / max(len(line), 1)
        word_count = len(line.split())
        digit_penalty = 0.25 if re.search(r"\d", line) else 0.0
        position_bonus = max(0.0, 1.0 - (idx * 0.12))
        score = (
            0.5 * alpha_ratio
            + 0.2 * min(word_count / 4.0, 1.0)
            + 0.3 * position_bonus
            - digit_penalty
        )
        scored_lines.append((score, line))

    if not scored_lines:
        return ""

    return max(scored_lines, key=lambda item: item[0])[1]


def _best_medicine_name(raw_text: str) -> str:
    """
    Infer medicine name from the first few lines of raw OCR output.

    Heuristic: the medicine name is typically:
        - In all-caps or Title Case
        - Near the top of the label
        - 1Ã¢â‚¬â€œ4 words long
        - NOT a date, batch, or dosage token
    """
    lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
    candidates = []
    search_lines = []
    label_line = _best_label_line(raw_text)
    if label_line:
        search_lines.append(label_line)
    search_lines.extend(lines[:6])  # inspect first 6 lines only

    for line in search_lines:
        m = _RE_NAME_CANDIDATES.findall(line)
        for candidate in m:
            # Reject obvious non-names
            if re.search(r"\d", candidate):
                continue
            if len(candidate) < 4:
                continue
            if any(hint in candidate.lower() for hint in _MEDICINE_HINTS):
                continue
            candidates.append(candidate)

    if not candidates:
        return ""

    # Return the most frequent candidate (multiple labels should agree)
    return Counter(candidates).most_common(1)[0][0].strip()


def _accept_ocr_text(text: str) -> str:
    """Reject obvious OCR garbage so weak regions do not pollute parsing."""
    text = (text or "").strip()
    if not text:
        return ""

    compact = re.sub(r"\s+", "", text)
    if len(compact) < 2:
        return ""

    alnum_ratio = sum(ch.isalnum() for ch in compact) / max(len(compact), 1)
    if alnum_ratio < 0.35:
        return ""

    return text


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _crop_percent_region(image_bgr: np.ndarray, top: float, bottom: float, left: float = 0.0, right: float = 1.0) -> np.ndarray:
    h, w = image_bgr.shape[:2]
    y1 = max(0, min(h, int(h * top)))
    y2 = max(0, min(h, int(h * bottom)))
    x1 = max(0, min(w, int(w * left)))
    x2 = max(0, min(w, int(w * right)))
    if y2 <= y1 or x2 <= x1:
        return image_bgr
    return image_bgr[y1:y2, x1:x2]


def _strict_match(pattern: re.Pattern, text: str) -> str:
    match = pattern.search(text or "")
    if not match:
        return ""
    if match.lastindex:
        value = next((group for group in match.groups() if group), "")
    else:
        value = match.group(0)
    return value.strip()


_RE_BATCH_STRICT = re.compile(
    r"\b(?:batch|batch\s*no\.?|b\.?no\.?|lot|lot\s*no\.?)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-\/]{2,})\b",
    re.IGNORECASE,
)
_RE_EXPIRY_STRICT = re.compile(
    r"\b(?:exp(?:iry)?|use\s*before|use\s*by)\s*[:\-]?\s*(\d{1,2}[\/\-]\d{2,4})\b",
    re.IGNORECASE,
)
_RE_MFG_STRICT = re.compile(
    r"\b(?:mfg|mfd|manufact(?:ured|ure(?:d)?)?)(?:\s*date)?\s*[:\-]?\s*(\d{1,2}[\/\-]\d{2,4})\b",
    re.IGNORECASE,
)
_RE_MANUFACTURER_STRICT = re.compile(
    r"\b([A-Za-z][A-Za-z0-9&'.,\-\s]{2,60}(?:ltd|limited|pvt|private|labs?|laboratories|pharma|pharmaceuticals?|healthcare|care|inc|corp|company)\.?)\b",
    re.IGNORECASE,
)


def _extract_medicine_name_from_text(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    candidates = []
    for idx, line in enumerate(lines[:5]):
        lower = line.lower()
        if any(hint in lower for hint in ("batch", "lot", "exp", "expiry", "mfg", "manufact", "mrp", "information")):
            continue
        if re.search(r"\d{2,}", line):
            continue
        alpha_ratio = sum(c.isalpha() for c in line) / max(len(line), 1)
        score = alpha_ratio + max(0.0, 1.0 - (idx * 0.15))
        if score > 0.9:
            candidates.append(line)
    if candidates:
        return candidates[0].strip().title()
    for line in lines[:3]:
        lower = line.lower()
        if any(hint in lower for hint in ("batch", "lot", "exp", "expiry", "mfg", "manufact", "mrp", "information")):
            continue
        if sum(c.isalpha() for c in line) < 3:
            continue
        if len(line) > 48:
            continue
        if len(line.split()) <= 4:
            return line.strip().title()
    if lines:
        filtered = [
            line
            for line in lines[:5]
            if not any(hint in line.lower() for hint in ("batch", "lot", "exp", "expiry", "mfg", "manufact", "mrp", "information"))
            and len(line) <= 48
            and sum(c.isalpha() for c in line) >= 3
        ]
        if filtered:
            best_line = max(
                filtered,
                key=lambda line: sum(c.isalpha() for c in line) / max(len(line), 1),
            )
            return best_line.strip().title()
    return _best_medicine_name(text)


def _extract_strict_batch(text: str) -> str:
    cleaned = clean_text(text).upper()
    candidates: list[str] = []
    for token in re.findall(r"[A-Z0-9\-]{5,}", cleaned):
        if not re.fullmatch(r"[A-Z0-9\-]{5,}", token):
            continue
        if not re.search(r"\d", token):
            continue
        if any(keyword in token.lower() for keyword in ("batch", "lot", "expiry", "exp", "mfg", "date")):
            continue
        candidates.append(token)
    if candidates:
        return max(candidates, key=len)
    return ""


def _fallback_batch_like(text: str) -> str:
    candidate = _best_batch(text or "")
    candidate = candidate.upper().strip()
    if not candidate:
        return ""
    if candidate in {"BATCH", "NUMBER", "LOT", "INFO", "INFORMATION"}:
        return ""
    if not re.search(r"\d", candidate):
        return ""
    return candidate


def _extract_strict_expiry(text: str) -> str:
    cleaned = clean_text(text)
    candidates: list[str] = []
    for match in re.finditer(r"\b(\d{1,2}[\/-]\d{2,4})\b", cleaned):
        candidate = _normalize_date_token(match.group(1))
        parsed = _parse_strict_date(candidate)
        if not parsed:
            continue
        if parsed.year < 2000 or parsed.year > 2100:
            continue
        if parsed < date.today():
            continue
        candidates.append(candidate)
    if candidates:
        return candidates[0]
    return ""


def _extract_strict_mfg(text: str) -> str:
    cleaned = clean_text(text)
    candidates: list[str] = []
    for match in re.finditer(r"\b(\d{1,2}[\/-]\d{2,4})\b", cleaned):
        candidate = _normalize_date_token(match.group(1))
        parsed = _parse_strict_date(candidate)
        if not parsed:
            continue
        if parsed.year < 2000 or parsed.year > 2100:
            continue
        if parsed > date.today():
            continue
        candidates.append(candidate)
    if candidates:
        return candidates[0]
    return ""


def _extract_strict_manufacturer(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""

    lower = raw.lower()
    if any(keyword in lower for keyword in ("batch", "expiry", "exp", "mfg", "mfd")):
        return ""
    digit_ratio = sum(ch.isdigit() for ch in raw) / max(len(raw), 1)
    if digit_ratio > 0.25:
        return ""
    if "." in raw and len(raw.split()) > 6:
        return ""

    matches = _RE_MANUFACTURER_STRICT.findall(raw)
    if not matches:
        return ""

    candidate = max(matches, key=len).strip().title()
    if sum(ch.isdigit() for ch in candidate) / max(len(candidate), 1) > 0.15:
        return ""
    if len(candidate.split()) > 10:
        return ""
    return candidate


def _prepare_region_for_token_ocr(region_bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    denoised = cv2.bilateralFilter(enhanced, 7, 50, 50)
    sharpen_kernel = np.array([[0, -1, 0], [-1, 6, -1], [0, -1, 0]], dtype=np.float32)
    sharpened = cv2.filter2D(denoised, -1, sharpen_kernel)
    return cv2.adaptiveThreshold(
        sharpened, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 15, 4
    )


def _extract_token_lines(region_bgr: np.ndarray) -> list[dict[str, Any]]:
    """LEGACY - NOT USED IN RUNTIME. Returns no OCR output."""
    return []

def _pair_line_candidates(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = list(lines)
    for idx in range(len(lines) - 1):
        first = lines[idx]
        second = lines[idx + 1]
        combined = f"{first['text']} {second['text']}".strip()
        candidates.append(
            {
                "key": (first["key"], second["key"]),
                "text": combined,
                "tokens": first["tokens"] + second["tokens"],
                "token_records": first.get("token_records", []) + second.get("token_records", []),
                "avg_conf": round((first["avg_conf"] + second["avg_conf"]) / 2.0, 4),
                "bbox": (
                    min(first["bbox"][0], second["bbox"][0]),
                    min(first["bbox"][1], second["bbox"][1]),
                    max(first["bbox"][2], second["bbox"][2]),
                    max(first["bbox"][3], second["bbox"][3]),
                ),
            }
        )
    return candidates


def _field_anchor_hit(text: str, anchors: set[str]) -> bool:
    token = _tokenize_anchor_text(text)
    return any(anchor in token for anchor in anchors)


def _normalize_candidate_text(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    text = re.sub(r"\s*([:/\-\.])\s*", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip(" -:/.")


def _token_window_candidates(lines: list[dict[str, Any]], field_name: str, anchors: set[str]) -> list[dict[str, Any]]:
    """Build reconstruction candidates from contiguous OCR token windows."""
    if not lines:
        return []

    max_window_by_field = {
        "medicine_name": 4,
        "manufacturer": 6,
        "batch_number": 5,
        "expiry_date": 4,
        "mfg_date": 4,
    }
    max_window = max_window_by_field.get(field_name, 4)
    candidates: list[dict[str, Any]] = []

    for line in lines:
        records = line.get("token_records") or [
            {
                "text": token_text,
                "conf": line.get("avg_conf", 0.0),
                "left": line["bbox"][0],
                "top": line["bbox"][1],
                "width": max(1, line["bbox"][2] - line["bbox"][0]),
                "height": max(1, line["bbox"][3] - line["bbox"][1]),
            }
            for token_text in line.get("tokens", [])
            if token_text
        ]
        if not records:
            continue

        line_anchor_hit = _field_anchor_hit(line.get("text", ""), anchors)
        token_count = len(records)
        for start in range(token_count):
            for end in range(start, min(token_count, start + max_window)):
                window = records[start : end + 1]
                raw_text = " ".join(str(token.get("text", "")).strip() for token in window if str(token.get("text", "")).strip())
                candidate_text = _normalize_candidate_text(raw_text)
                if not candidate_text:
                    continue
                conf_values = [
                    float(token.get("conf", -1.0))
                    for token in window
                    if float(token.get("conf", -1.0)) >= 0
                ]
                avg_conf = sum(conf_values) / len(conf_values) if conf_values else float(line.get("avg_conf", 0.0))
                x1 = min(int(token.get("left", 0)) for token in window)
                y1 = min(int(token.get("top", 0)) for token in window)
                x2 = max(int(token.get("left", 0)) + int(token.get("width", 0)) for token in window)
                y2 = max(int(token.get("top", 0)) + int(token.get("height", 0)) for token in window)
                candidates.append(
                    {
                        "key": (line.get("key"), start, end),
                        "text": candidate_text,
                        "tokens": [str(token.get("text", "")) for token in window if str(token.get("text", "")).strip()],
                        "token_records": window,
                        "avg_conf": round(avg_conf, 4),
                        "bbox": (x1, y1, x2, y2),
                        "line_anchor_hit": line_anchor_hit,
                    }
                )

    return candidates


def _score_reconstructed_candidate(candidate: str, field_name: str, avg_conf: float, anchor_hit: bool) -> float:
    candidate = (candidate or "").strip()
    if not candidate:
        return 0.0

    text = candidate.upper()
    lower = text.lower()
    alnum = sum(ch.isalnum() for ch in text)
    alpha = sum(ch.isalpha() for ch in text)
    digits = sum(ch.isdigit() for ch in text)
    length = len(text)
    base = 0.25 * _clamp(avg_conf) + 0.20 * _clamp(alnum / max(length, 1)) + 0.15 * _clamp(length / 24.0)

    if field_name == "batch_number":
        if any(bad in lower for bad in ("expiry", "exp ", "mfg", "mfd", "manufact", "date")):
            return 0.0
        if not anchor_hit and (" " in text or len(text) > 24):
            return 0.0
        if digits == 0 or alpha == 0:
            return 0.0
        if re.fullmatch(r"\d{4}", text):
            return 0.0
        if not anchor_hit and not re.fullmatch(r"[A-Z0-9][A-Z0-9\-\/\.]{2,24}", text):
            return 0.0
        pattern_bonus = 0.35 if re.search(r"[A-Z]\d|\d[A-Z]", text) else 0.15
        separator_bonus = 0.15 if any(sep in text for sep in ("-", "/", ".")) else 0.0
        anchor_bonus = 0.15 if anchor_hit else 0.0
        return round(_clamp(base + pattern_bonus + separator_bonus + anchor_bonus), 4)

    if field_name in {"expiry_date", "mfg_date"}:
        if not anchor_hit:
            return 0.0
        if field_name == "expiry_date" and any(bad in lower for bad in ("batch", "lot", "mfg", "mfd", "manufactured")):
            return 0.0
        if field_name == "mfg_date" and any(bad in lower for bad in ("batch", "lot", "expiry", "exp")):
            return 0.0
        if re.fullmatch(r"\d{4}", text):
            return 0.0
        date_match = re.search(r"\b(\d{1,2}[/-]\d{2,4}|\d{4})\b", text)
        if not date_match:
            return 0.0
        pattern_bonus = 0.45 if re.search(r"\d{1,2}[/-]\d{2,4}", text) else 0.10
        anchor_bonus = 0.20 if anchor_hit else 0.0
        return round(_clamp(base + pattern_bonus + anchor_bonus), 4)

    if field_name == "manufacturer":
        if re.search(r"\b\d{1,2}[/-]\d{2,4}\b", text):
            return 0.0
        if any(bad in lower for bad in ("batch", "expiry", "exp ", "mfg", "mfd")):
            return 0.0
        if any(hint in lower for hint in ("tablet", "capsule", "syrup", "injection", "medicine", "vitamin")):
            return 0.0
        suffix_bonus = 0.35 if _RE_MANUFACTURER_STRICT.search(text) else 0.0
        word_bonus = 0.15 if len(text.split()) >= 2 else 0.0
        return round(_clamp(base + suffix_bonus + word_bonus + (0.10 if anchor_hit else 0.0)), 4)

    if field_name == "medicine_name":
        if digits > 2:
            return 0.0
        if any(hint in lower for hint in ("batch", "exp", "expiry", "mfg", "manufact", "information")):
            return 0.0
        word_bonus = 0.15 if 1 <= len(text.split()) <= 4 else 0.0
        return round(_clamp(base + word_bonus + (0.10 if anchor_hit else 0.0)), 4)

    return round(_clamp(base + (0.10 if anchor_hit else 0.0)), 4)


def _select_field_candidate(
    lines: list[dict[str, Any]],
    field_name: str,
    anchors: set[str],
    *,
    min_score: float,
) -> tuple[str, float, dict[str, Any] | None]:
    if field_name == "medicine_name":
        candidates = _pair_line_candidates(lines) + _token_window_candidates(lines, field_name, anchors)
    else:
        candidates = _token_window_candidates(lines, field_name, anchors)
    seen_texts: set[str] = set()
    best_text = ""
    best_score = 0.0
    best_meta: dict[str, Any] | None = None

    for candidate in candidates:
        text = candidate["text"]
        text_key = _normalize_candidate_text(text).lower()
        if not text_key or text_key in seen_texts:
            continue
        seen_texts.add(text_key)
        anchor_hit = _field_anchor_hit(text, anchors)
        anchor_hit = anchor_hit or bool(candidate.get("line_anchor_hit"))
        score = _score_reconstructed_candidate(text, field_name, candidate["avg_conf"], anchor_hit)
        if score > best_score:
            best_score = score
            best_text = text
            best_meta = candidate

    if best_score < min_score:
        return "", 0.0, None
    return best_text.strip(), round(best_score, 4), best_meta


def _tokenize_anchor_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _detect_anchor_regions(preprocessed_image: np.ndarray, anchor_keywords: set[str]) -> list[dict[str, int]]:
    """LEGACY - NOT USED IN RUNTIME. Returns no OCR output."""
    return []

def _expand_region(image_bgr: np.ndarray, box: dict[str, int], *, left_pad: int = 20, right_pad: int = 220, top_pad: int = 30, bottom_pad: int = 60) -> np.ndarray:
    h, w = image_bgr.shape[:2]
    x1 = max(0, box["x1"] - left_pad)
    y1 = max(0, box["y1"] - top_pad)
    x2 = min(w, box["x2"] + right_pad)
    y2 = min(h, box["y2"] + bottom_pad)
    if x2 <= x1 or y2 <= y1:
        return image_bgr
    return image_bgr[y1:y2, x1:x2]


def _best_region_by_anchors(
    image_bgr: np.ndarray,
    preprocessed_image: np.ndarray,
    anchors: set[str],
    *,
    fallback_region: tuple[float, float] | None = None,
    expansion: dict[str, int] | None = None,
) -> np.ndarray:
    boxes = _detect_anchor_regions(preprocessed_image, anchors)
    expansion = expansion or {}
    if boxes:
        # Use the first / highest-left anchor on the page to avoid grabbing
        # unrelated footer text.
        box = sorted(boxes, key=lambda item: (item["y1"], item["x1"]))[0]
        return _expand_region(image_bgr, box, **expansion)
    if fallback_region is not None:
        top, bottom = fallback_region
        return _crop_percent_region(image_bgr, top, bottom)
    return image_bgr


def preprocess_image(image_input) -> np.ndarray:
    return _preprocess_image_strict(image_input)


def extract_text_from_region(region_bgr: np.ndarray, target_field: str = "general") -> str:
    """LEGACY - NOT USED IN RUNTIME. Returns no OCR output."""
    return ""

def extract_text(preprocessed_image: np.ndarray) -> str:
    """LEGACY - NOT USED IN RUNTIME. Returns no OCR output."""
    return ""

def _detect_anchor_regions(preprocessed_image: np.ndarray, anchor_keywords: set[str]) -> list[dict[str, int]]:
    """LEGACY - NOT USED IN RUNTIME. Returns no OCR output."""
    return []

def _extract_token_lines(region_bgr: np.ndarray) -> list[dict[str, Any]]:
    """LEGACY - NOT USED IN RUNTIME. Returns no OCR output."""
    return []

def extract_fields_structured(image_bgr: np.ndarray, original_raw_text: str = "") -> MedicineFields:
    """
    Structured OCR that treats the medicine pack as fixed regions.

    Top region: medicine name
    Middle region: manufacturer / composition
    Bottom region: batch / expiry / mfg
    """
    preprocessed = preprocess_image(image_bgr)
    full_text = _accept_ocr_text(extract_text(preprocessed))
    original_text = _accept_ocr_text(original_raw_text)

    name_region = _best_region_by_anchors(
        image_bgr,
        preprocessed,
        anchors={"medicine", "tablet", "capsule", "syrup", "injection"},
        fallback_region=(0.0, 0.35),
        expansion={"left_pad": 15, "right_pad": 140, "top_pad": 18, "bottom_pad": 48},
    )
    middle_region = _best_region_by_anchors(
        image_bgr,
        preprocessed,
        anchors={"manufacturer", "manufactured", "pharma", "labs", "healthcare"},
        fallback_region=(0.20, 0.72),
        expansion={"left_pad": 15, "right_pad": 200, "top_pad": 24, "bottom_pad": 56},
    )
    batch_region = _best_region_by_anchors(
        image_bgr,
        preprocessed,
        anchors={"batch", "lot", "bno", "batchno", "b/no"},
        fallback_region=(0.45, 1.00),
        expansion={"left_pad": 20, "right_pad": 260, "top_pad": 20, "bottom_pad": 160},
    )
    expiry_region = _best_region_by_anchors(
        image_bgr,
        preprocessed,
        anchors={"exp", "expiry", "usebefore", "useby"},
        fallback_region=(0.45, 1.00),
        expansion={"left_pad": 20, "right_pad": 260, "top_pad": 20, "bottom_pad": 160},
    )
    mfg_region = _best_region_by_anchors(
        image_bgr,
        preprocessed,
        anchors={"mfg", "mfd", "manufactured", "manufacture"},
        fallback_region=(0.35, 1.00),
        expansion={"left_pad": 20, "right_pad": 260, "top_pad": 20, "bottom_pad": 160},
    )

    name_lines = _extract_token_lines(name_region)
    middle_lines = _extract_token_lines(middle_region)
    batch_lines = _extract_token_lines(batch_region)
    expiry_lines = _extract_token_lines(expiry_region)
    mfg_lines = _extract_token_lines(mfg_region)

    fields = MedicineFields(raw_text="\n".join([full_text, original_text]).strip())
    fields.qr_data = extract_qr_data(image_bgr)
    failure_map: dict[str, str] = {
        "medicine_name": "NO_ANCHOR",
        "batch_number": "NO_ANCHOR",
        "expiry_date": "NO_ANCHOR",
        "mfg_date": "NO_ANCHOR",
        "manufacturer": "NO_ANCHOR",
    }

    name_candidate, name_score, _ = _select_field_candidate(
        name_lines,
        "medicine_name",
        anchors={"medicine", "tablet", "capsule", "syrup", "injection"},
        min_score=0.65,
    )
    batch_candidate, batch_score, _ = _select_field_candidate(
        batch_lines,
        "batch_number",
        anchors={"batch", "lot", "bno", "batchno", "b/no"},
        min_score=0.65,
    )
    expiry_candidate, expiry_score, _ = _select_field_candidate(
        expiry_lines,
        "expiry_date",
        anchors={"exp", "expiry", "usebefore", "useby"},
        min_score=0.65,
    )
    mfg_candidate, mfg_score, _ = _select_field_candidate(
        mfg_lines,
        "mfg_date",
        anchors={"mfg", "mfd", "manufactured", "manufacture"},
        min_score=0.65,
    )
    manufacturer_candidate, manufacturer_score, _ = _select_field_candidate(
        middle_lines,
        "manufacturer",
        anchors={"manufacturer", "manufactured", "pharma", "labs", "healthcare"},
        min_score=0.65,
    )

    # Medicine name: accept only strong top-region candidates.
    if name_candidate and name_score >= 0.65:
        fields.medicine_name = name_candidate
        fields.medicine_name_confidence = round(_clamp(name_score), 4)
        failure_map["medicine_name"] = ""
    else:
        fields.medicine_name = ""
        fields.medicine_name_confidence = round(_clamp(name_score), 4)
        failure_map["medicine_name"] = "LOW_CONFIDENCE" if name_lines else "NO_ANCHOR"

    # Batch: token-window candidate must satisfy strict structure.
    if batch_candidate and _is_valid_batch_value(batch_candidate) and batch_score >= 0.65:
        fields.batch_number = batch_candidate.upper().strip()
        fields.batch_confidence = round(_clamp(batch_score), 4)
        failure_map["batch_number"] = ""
    elif batch_candidate and not _is_valid_batch_value(batch_candidate):
        fields.batch_number = ""
        fields.batch_confidence = round(_clamp(batch_score), 4)
        failure_map["batch_number"] = "INVALID_FORMAT"
    elif batch_candidate:
        fields.batch_number = ""
        fields.batch_confidence = round(_clamp(batch_score), 4)
        failure_map["batch_number"] = "LOW_CONFIDENCE"
    else:
        fields.batch_number = ""
        fields.batch_confidence = 0.0
        failure_map["batch_number"] = "NO_ANCHOR"

    # Expiry: accept only anchored, valid date tokens.
    if expiry_candidate:
        normalized_expiry = _normalize_date_token(expiry_candidate)
        expiry_valid, expiry_conf, expiry_reason = _date_confidence_gate(normalized_expiry, True, expiry_score)
        if expiry_valid:
            fields.expiry_date = normalized_expiry
            fields.expiry_confidence = expiry_conf
            failure_map["expiry_date"] = ""
        else:
            fields.expiry_date = ""
            fields.expiry_confidence = expiry_conf
            failure_map["expiry_date"] = expiry_reason
    else:
        fields.expiry_date = ""
        fields.expiry_confidence = 0.0
        failure_map["expiry_date"] = "NO_ANCHOR"

    # MFG: accept only anchored, valid date tokens.
    if mfg_candidate:
        normalized_mfg = _normalize_date_token(mfg_candidate)
        mfg_valid, mfg_conf, mfg_reason = _date_confidence_gate(normalized_mfg, True, mfg_score)
        if mfg_valid:
            fields.mfg_date = normalized_mfg
            fields.mfg_confidence = mfg_conf
            failure_map["mfg_date"] = ""
        else:
            fields.mfg_date = ""
            fields.mfg_confidence = mfg_conf
            failure_map["mfg_date"] = mfg_reason
    else:
        fields.mfg_date = ""
        fields.mfg_confidence = 0.0
        failure_map["mfg_date"] = "NO_ANCHOR"

    # Manufacturer: anchor + company-block validation only.
    if manufacturer_candidate and _is_valid_manufacturer_value(manufacturer_candidate) and manufacturer_score >= 0.65:
        fields.manufacturer = manufacturer_candidate.strip()
        fields.manufacturer_confidence = round(_clamp(manufacturer_score), 4)
        failure_map["manufacturer"] = ""
    elif manufacturer_candidate and not _is_valid_manufacturer_value(manufacturer_candidate):
        fields.manufacturer = ""
        fields.manufacturer_confidence = round(_clamp(manufacturer_score), 4)
        failure_map["manufacturer"] = "INVALID_FORMAT"
    elif manufacturer_candidate:
        fields.manufacturer = ""
        fields.manufacturer_confidence = round(_clamp(manufacturer_score), 4)
        failure_map["manufacturer"] = "LOW_CONFIDENCE"
    else:
        fields.manufacturer = ""
        fields.manufacturer_confidence = 0.0
        failure_map["manufacturer"] = "NO_ANCHOR"

    # Cross-field relation validation: expiry must be after mfg.
    parsed_expiry = _parse_strict_date(fields.expiry_date) if fields.expiry_date else None
    parsed_mfg = _parse_strict_date(fields.mfg_date) if fields.mfg_date else None
    if parsed_expiry and parsed_mfg and parsed_expiry <= parsed_mfg:
        fields.expiry_date = ""
        fields.mfg_date = ""
        fields.expiry_confidence = 0.0
        fields.mfg_confidence = 0.0
        failure_map["expiry_date"] = "INVALID_FORMAT"
        failure_map["mfg_date"] = "INVALID_FORMAT"

    fields = normalize_extracted_fields(fields)
    fields.failure_map = failure_map
    fields.confidence = _compute_field_confidence(fields)
    return fields


# ---------------------------------------------------------------------------
# STAGE 4.5 Ã¢â‚¬â€ FIELD-FOCUSED EXTRACTION & POST-PROCESSING
# ---------------------------------------------------------------------------

def normalize_extracted_fields(fields: MedicineFields) -> MedicineFields:
    """
    Apply post-processing rules to normalize field values.
    
    Rules:
        - Normalize date formats (ensure MM/YYYY)
        - Remove common abbreviations (EXPÃ¢â€ â€™expiry, B.NoÃ¢â€ â€™batch)
        - Clean manufacturer names (remove suffixes)
    """
    # Expiry date normalization
    if fields.expiry_date:
        exp_text = fields.expiry_date.strip()
        # Replace common abbreviations
        exp_text = re.sub(r'\bexp(?:\.|:)?\s*', '', exp_text, flags=re.IGNORECASE)
        exp_text = re.sub(r'\bexpiry(?:\s*date)?\s*', '', exp_text, flags=re.IGNORECASE)
        exp_text = re.sub(r'\buse\s*by\s*', '', exp_text, flags=re.IGNORECASE)
        fields.expiry_date = exp_text.strip()
    
    # Batch number normalization
    if fields.batch_number:
        batch_text = fields.batch_number.strip()
        batch_text = re.sub(r'\bbatch\s*no\.?\s*:?\s*', '', batch_text, flags=re.IGNORECASE)
        batch_text = re.sub(r'\blot\s*no\.?\s*:?\s*', '', batch_text, flags=re.IGNORECASE)
        batch_text = re.sub(r'\bb/n\s*:?\s*', '', batch_text, flags=re.IGNORECASE)
        batch_text = re.sub(r'\bb\.no\s*:?\s*', '', batch_text, flags=re.IGNORECASE)
        fields.batch_number = batch_text.strip()
    
    # Manufacturer normalization (remove Ltd, Inc, pvt, etc.)
    if fields.manufacturer:
        manuf_text = fields.manufacturer.strip()
        manuf_text = re.sub(r'\s*(ltd|inc|pvt|pvt\.?|llc|corp|co|company)\.?\s*$', '', 
                           manuf_text, flags=re.IGNORECASE).strip()
        fields.manufacturer = manuf_text.title()
    
    # Medicine name normalization
    if fields.medicine_name:
        fields.medicine_name = fields.medicine_name.strip().title()
    
    return fields


def extract_fields_region_based(image_bgr: np.ndarray, original_raw_text: str) -> MedicineFields:
    """
    Extract fields using region-specific OCR with field-focused patterns.
    
    Strategy:
        1. Crop region for medicine name (top) Ã¢â€ â€™ run OCR on it
        2. Crop region for batch/expiry (bottom) Ã¢â€ â€™ run OCR on it
        3. Try pattern matching in regions first, then fallback to full text
    """
    # Preprocess for region detection
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    binary = cv2.adaptiveThreshold(
        blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 11, 2
    )
    
    fields = MedicineFields(raw_text=original_raw_text)
    
    # Ã¢â€â‚¬Ã¢â€â‚¬ Extract medicine name from top region Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    name_region = crop_region_for_medicine_name(image_bgr, binary)
    if name_region is not None:
        name_text = extract_text_from_region(name_region, target_field='name')
        name_cleaned = clean_text(name_text)
        fields.medicine_name = _best_medicine_name(name_text or original_raw_text)
    else:
        fields.medicine_name = _best_medicine_name(original_raw_text)
    
    # Ã¢â€â‚¬Ã¢â€â‚¬ Extract batch/expiry from bottom region Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    batch_region = crop_region_for_batch_expiry(image_bgr, binary)
    batch_expiry_text = ""
    if batch_region is not None:
        batch_expiry_text = extract_text_from_region(batch_region, target_field='batch')
    
    # Combine region text with original for pattern matching
    search_text = clean_text(batch_expiry_text or original_raw_text)
    
    # Ã¢â€â‚¬Ã¢â€â‚¬ Field-focused extraction (batch FIRST, then expiry) Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    fields.batch_number = _best_batch(search_text)
    fields.expiry_date = _best_date(_RE_EXPIRY, search_text)
    fields.mfg_date = _best_date(_RE_MFG, search_text)
    fields.manufacturer = _best_manufacturer(search_text)
    
    # Fallback for expiry from standalone dates if not found in patterns
    if not fields.expiry_date:
        standalone_dates = _RE_DATE_STANDALONE.findall(search_text)
        if standalone_dates:
            fields.expiry_date = f"{standalone_dates[0][0].zfill(2)}/{standalone_dates[0][1]}"
    
    # Extract QR from original image
    fields.qr_data = extract_qr_data(image_bgr)
    
    # Apply post-processing normalization
    fields = normalize_extracted_fields(fields)
    
    # Compute confidence
    fields.confidence = _compute_field_confidence(fields)
    
    return fields


def _score_field_confidence(
    extracted_text: str,
    ocr_score: float,
    anchor_hit: bool,
    regex_hit: bool,
    field_name: str,
) -> float:
    """
    Field-level confidence from OCR clarity, anchor proximity, and match strength.
    """
    text = (extracted_text or "").strip()
    if not text:
        return 0.0

    alnum_ratio = sum(ch.isalnum() for ch in text) / max(len(text), 1)
    length_score = _clamp(len(text) / 40.0)
    clarity = _clamp(ocr_score)
    anchor_score = 1.0 if anchor_hit else 0.45
    regex_score = 1.0 if regex_hit else (0.65 if field_name == "medicine_name" else 0.35)

    if field_name == "medicine_name":
        regex_score = 0.75 if regex_hit else 0.5

    score = (
        0.35 * clarity +
        0.25 * anchor_score +
        0.25 * regex_score +
        0.15 * max(alnum_ratio, length_score)
    )
    return round(_clamp(score), 4)


def _compute_field_confidence(fields: MedicineFields) -> float:
    """
    Overall extraction confidence from per-field confidence and completeness.
    """
    field_scores = [
        fields.medicine_name_confidence,
        fields.batch_confidence,
        fields.expiry_confidence,
        fields.mfg_confidence,
        fields.manufacturer_confidence,
    ]
    non_zero = [score for score in field_scores if score > 0]
    if non_zero:
        return round(sum(non_zero) / len(non_zero), 4)

    completeness = 0.0
    completeness += 0.2 if fields.medicine_name.strip() else 0.0
    completeness += 0.2 if fields.batch_number.strip() else 0.0
    completeness += 0.2 if fields.expiry_date.strip() else 0.0
    completeness += 0.2 if fields.mfg_date.strip() else 0.0
    completeness += 0.2 if fields.manufacturer.strip() else 0.0

    if fields.qr_data.strip():
        completeness = min(1.0, completeness + 0.1)

    return round(completeness, 4)


def extract_fields(raw_text: str) -> MedicineFields:
    """
    Parse all structured fields from raw OCR text.

    Args:
        raw_text: Raw (uncleaned) OCR string.

    Returns:
        MedicineFields dataclass.
    """
    fields = MedicineFields()
    fields.raw_text = raw_text

    pools = _build_token_pools(raw_text)
    fields.medicine_name, fields.medicine_name_confidence = _select_token_candidate(pools["medicine_name"], "medicine_name", raw_text)
    fields.batch_number, fields.batch_confidence = _select_token_candidate(pools["batch_number"], "batch_number", raw_text)
    fields.expiry_date, fields.expiry_confidence = _select_token_candidate(pools["expiry_date"], "expiry_date", raw_text)
    fields.mfg_date, fields.mfg_confidence = _select_token_candidate(pools["mfg_date"], "mfg_date", raw_text)
    fields.manufacturer, fields.manufacturer_confidence = _select_token_candidate(pools["manufacturer"], "manufacturer", raw_text)

    if fields.expiry_date:
        fields.expiry_date = _normalize_date_token(fields.expiry_date)
    if fields.mfg_date:
        fields.mfg_date = _normalize_date_token(fields.mfg_date)
    if fields.batch_number:
        fields.batch_number = fields.batch_number.upper().strip()
    if fields.manufacturer:
        fields.manufacturer = fields.manufacturer.strip()
    if fields.medicine_name:
        fields.medicine_name = fields.medicine_name.strip()

    fields.confidence = compute_confidence(fields, raw_text)

    return fields


def _parse_month_year(value: str, *, as_end_of_month: bool = False) -> date | None:
    """Parse MM/YY or MM/YYYY strings into a date for validation."""
    value = (value or "").strip()
    m = re.fullmatch(r"(\d{1,2})/(\d{2}|\d{4})", value)
    if not m:
        return None

    month = int(m.group(1))
    year_part = m.group(2)
    year = int(year_part)
    if len(year_part) == 2:
        year += 2000

    if not 1 <= month <= 12:
        return None

    if as_end_of_month:
        from calendar import monthrange

        return date(year, month, monthrange(year, month)[1])
    return date(year, month, 1)


def validate_fields(fields: MedicineFields, raw_text: str = "") -> ValidationResult:
    """
    Validate OCR output for obviously invalid or suspicious metadata.

    This does not prove a medicine is fake. It only flags OCR and packaging
    issues that are worth showing to the user.
    """
    issues: list[str] = []
    penalties = 0.0
    today = date.today()

    required_fields = {
        "medicine_name": "medicine name missing",
        "batch_number": "batch number missing",
        "expiry_date": "expiry date missing",
        "mfg_date": "manufacturing date missing",
        "manufacturer": "manufacturer missing",
    }

    for field_name, issue_text in required_fields.items():
        if not getattr(fields, field_name).strip():
            issues.append(issue_text)
            penalties += 0.15

    mfg_date = _parse_strict_date(fields.mfg_date)
    exp_date = _parse_strict_date(fields.expiry_date)

    if fields.mfg_date and not mfg_date:
        issues.append("manufacturing date format is invalid")
        penalties += 0.15
    if fields.expiry_date and not exp_date:
        issues.append("expiry date format is invalid")
        penalties += 0.15

    if mfg_date and mfg_date > today:
        issues.append("manufacturing date is in the future")
        penalties += 0.25
    if exp_date and exp_date < today:
        issues.append("expiry date has already passed")
        penalties += 0.25
    if mfg_date and exp_date and mfg_date > exp_date:
        issues.append("manufacturing date is later than expiry date")
        penalties += 0.25

    if raw_text and len(raw_text.strip()) < 20:
        issues.append("ocr text is too short to trust confidently")
        penalties += 0.1

    score = max(0.0, 1.0 - penalties)
    return ValidationResult(
        validation_score=round(score, 4),
        issue_count=len(issues),
        issues=issues,
    )


# ---------------------------------------------------------------------------
# STAGE 5 Ã¢â‚¬â€ Validation + Per-Image Confidence
# ---------------------------------------------------------------------------

CORE_FIELD_NAMES = ["medicine_name", "batch_number", "expiry_date", "mfg_date", "manufacturer"]
OPTIONAL_FIELD_NAMES = ["qr_data"]


def compute_confidence(fields: MedicineFields, raw_text: str) -> float:
    """
    Estimate extraction confidence for a single image on a 0Ã¢â‚¬â€œ1 scale.

    Components:
        - field_ratio   : fraction of the 5 key fields successfully extracted
        - text_density  : ratio of alphanumeric chars to total chars in raw OCR
                          (low density Ã¢â€ â€™ noisy, blurry image)
        - length_bonus  : non-empty OCR output is a positive signal

    Formula:
        confidence = 0.6 * field_ratio + 0.3 * text_density + 0.1 * length_bonus
    """
    extracted = sum(1 for f in CORE_FIELD_NAMES if getattr(fields, f))
    field_ratio = extracted / len(CORE_FIELD_NAMES)

    if raw_text:
        alnum_chars = sum(c.isalnum() for c in raw_text)
        text_density = min(alnum_chars / max(len(raw_text), 1), 1.0)
        length_bonus = min(len(raw_text) / 200, 1.0)
    else:
        text_density = 0.0
        length_bonus = 0.0

    confidence = (0.6 * field_ratio) + (0.3 * text_density) + (0.1 * length_bonus)
    return round(confidence, 4)


# ---------------------------------------------------------------------------
# STAGE 6 Ã¢â‚¬â€ Multi-Image Fusion
# ---------------------------------------------------------------------------

def _normalize_for_field(field_name: str, value: str) -> str:
    """Normalize values before voting so formatting does not create noise."""
    value = (value or "").strip()
    if not value:
        return ""
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s*([:/\-\.])\s*", r"\1", value)
    if field_name == "batch_number":
        value = re.sub(r"^(?:batch|lot|b/?no\.?)\s*[:\-]?\s*", "", value, flags=re.IGNORECASE)
        return value.upper()
    if field_name in {"expiry_date", "mfg_date"}:
        value = re.sub(r"^(?:exp(?:iry)?|mfg|mfd|use\s*by|use\s*before)(?:\s*date)?\s*[:\-]?\s*", "", value, flags=re.IGNORECASE)
        return _normalize_date_token(value)
    if field_name == "manufacturer":
        value = re.sub(r"^(?:manufacturer|mfr|by)\s*[:\-]?\s*", "", value, flags=re.IGNORECASE)
        return value.title()
    if field_name == "medicine_name":
        value = re.sub(r"^(?:medicine|name)\s*[:\-]?\s*", "", value, flags=re.IGNORECASE)
        return value.title()
    if field_name == "qr_data":
        return value
    return value


def _weighted_majority(values: list[str], weights: list[float], field_name: str = "") -> str:
    """
    Return the value with the highest combined weight.
    Empty strings are excluded from voting.

    Args:
        values:  candidate values from each image
        weights: confidence score per image

    Returns:
        Winning value string or "" if no candidates.
    """
    vote: dict[str, float] = {}
    for v, w in zip(values, weights):
        v = _normalize_for_field(field_name, v)
        if v:
            vote[v] = vote.get(v, 0.0) + w

    if not vote:
        return ""
    return max(vote, key=vote.get)


def _field_threshold(field_name: str) -> float:
    if field_name == "batch_number":
        return 0.78
    if field_name == "expiry_date":
        return 0.46
    if field_name == "mfg_date":
        return 0.52
    if field_name == "medicine_name":
        return 0.56
    if field_name == "manufacturer":
        return 0.48
    return 0.60


def _field_tier(field_name: str, normalized_values: list[str], scores: list[float], chosen: str) -> int:
    if not chosen:
        return 4
    exact_support = sum(1 for value in normalized_values if value == chosen)
    if exact_support >= 2:
        return 1
    if any(value == chosen for value in normalized_values):
        return 2
    if max(scores) >= _field_threshold(field_name):
        return 3
    return 4


def _medicine_similarity(left: str, right: str) -> float:
    left_norm = re.sub(r"\s+", "", _normalize_for_field("medicine_name", left).lower())
    right_norm = re.sub(r"\s+", "", _normalize_for_field("medicine_name", right).lower())
    if not left_norm or not right_norm:
        return 0.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def _collect_image_pools(per_image: list[MedicineFields]) -> list[dict[str, list[dict[str, Any]]]]:
    return [_build_token_pools(getattr(image, "raw_text", "")) for image in per_image]


def _image_supports_identity(pools: dict[str, list[dict[str, Any]]], identity: str) -> bool:
    identity = _normalize_for_field("medicine_name", identity)
    if not identity:
        return False

    for item in pools.get("medicine_name", []):
        token = str(item.get("token", "")).strip()
        normalized = _normalize_for_field("medicine_name", token)
        if not normalized:
            continue
        if normalized == identity or _medicine_similarity(normalized, identity) >= 0.86:
            return True
    return False


def _cluster_medicine_candidates(candidates: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    clusters: list[list[dict[str, Any]]] = []
    for item in sorted(candidates, key=lambda entry: (entry["score"], entry["image_weight"]), reverse=True):
        placed = False
        for cluster in clusters:
            if any(_medicine_similarity(item["normalized"], member["normalized"]) >= 0.84 for member in cluster):
                cluster.append(item)
                placed = True
                break
        if not placed:
            clusters.append([item])
    return clusters


def _manufacturer_similarity(left: str, right: str) -> float:
    left_norm = re.sub(r"\s+", "", _normalize_for_field("manufacturer", left).lower())
    right_norm = re.sub(r"\s+", "", _normalize_for_field("manufacturer", right).lower())
    if not left_norm or not right_norm:
        return 0.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def _cluster_manufacturer_candidates(candidates: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    clusters: list[list[dict[str, Any]]] = []
    for item in sorted(candidates, key=lambda entry: (entry["score"], entry["image_weight"]), reverse=True):
        placed = False
        for cluster in clusters:
            if any(_manufacturer_similarity(item["normalized"], member["normalized"]) >= 0.84 for member in cluster):
                cluster.append(item)
                placed = True
                break
        if not placed:
            clusters.append([item])
    return clusters


def _is_plausible_medicine_name(value: str, cluster: list[dict[str, Any]] | None = None) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    lower = text.lower()
    if re.search(r"\d", text):
        return False
    if lower in _MEDICINE_NAME_STOPWORDS:
        return False
    if any(hint in lower for hint in ("batch", "exp", "expiry", "mfg", "manufact", "tablet", "capsule")):
        return False
    if len(text) < 3 or len(text) > 32:
        return False
    if cluster:
        strong_alpha_support = sum(
            1
            for item in cluster
            if re.fullmatch(r"[A-Za-z][A-Za-z&'\- ]{2,32}", str(item.get("token", "")).strip())
            and _medicine_name_quality_score(str(item.get("token", "")), str(item.get("line_text", ""))) >= 0.08
        )
        if strong_alpha_support == 0:
            return False
    return True


def _is_plausible_manufacturer_value(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    lower = text.lower()
    if re.search(r"\b\d{1,2}[/-]\d{2,4}\b", text):
        return False
    if any(hint in lower for hint in ("batch", "expiry", "exp ", "mfg", "mfd", "tablet", "capsule", "syrup", "injection")):
        return False
    if len(text) < 3 or len(text) > 48:
        return False
    if any(suffix in lower for suffix in ("ltd", "limited", "pharma", "pharmaceuticals", "labs", "laboratories", "company", "corp", "inc", "pvt", "healthcare", "care")):
        return True
    if re.fullmatch(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+", text):
        return True
    if re.fullmatch(r"[A-Za-z][A-Za-z&'\- ]{2,48}", text):
        return True
    return False


def _fusion_region_bonus(field_name: str, region_origin: str, token: str = "", line_text: str = "") -> float:
    text = f"{token} {line_text}".lower()
    origin = (region_origin or "full").lower()
    score = 0.0

    if field_name == "batch_number":
        score += {"top": 0.02, "middle": 0.12, "bottom": 0.18, "full": 0.08}.get(origin, 0.06)
        if any(hint in text for hint in ("batch", "lot", "b no", "batch no", "lot no")):
            score += 0.06
    elif field_name == "expiry_date":
        score += {"top": 0.02, "middle": 0.08, "bottom": 0.20, "full": 0.06}.get(origin, 0.05)
        if any(hint in text for hint in ("exp", "expiry", "best before", "use by", "use before")):
            score += 0.08
    elif field_name == "mfg_date":
        score += {"top": 0.02, "middle": 0.10, "bottom": 0.18, "full": 0.06}.get(origin, 0.05)
        if any(hint in text for hint in ("mfg", "mfd", "manufactured", "manufacture", "use by", "exp")):
            score += 0.08
    elif field_name == "manufacturer":
        score += {"top": 0.16, "middle": 0.14, "bottom": 0.04, "full": 0.08}.get(origin, 0.06)
        if any(hint in text for hint in ("ltd", "limited", "pharma", "labs", "healthcare", "company", "corp", "inc", "pvt")):
            score += 0.08
    elif field_name == "medicine_name":
        score += {"top": 0.18, "middle": 0.08, "bottom": 0.02, "full": 0.10}.get(origin, 0.05)

    return round(min(score, 0.3), 4)


def _fusion_score_components(
    field_name: str,
    group: list[dict[str, Any]],
    total_images: int,
) -> dict[str, Any]:
    if not group:
        return {
            "token_consensus_score": 0.0,
            "cross_image_agreement": 0.0,
            "region_spatial_confidence": 0.0,
            "structure_score": 0.0,
            "region_weight_contribution": 0.0,
            "final_field_score": 0.0,
            "support_images": 0,
            "support_ratio": 0.0,
        }

    support_images = len({item["image_index"] for item in group})
    total_images = max(total_images, 1)
    token_consensus_score = sum(
        float(item.get("lexical_score", item.get("score", 0.0)))
        for item in group
    ) / max(len(group), 1)
    cross_image_agreement = support_images / total_images
    region_spatial_confidence = sum(
        min(
            1.0,
            float(item.get("spatial_score", 0.0))
            + _fusion_region_bonus(
                field_name,
                str(item.get("region_origin", "full")),
                str(item.get("token", "")),
                str(item.get("line_text", "")),
            ),
        )
        for item in group
    ) / max(len(group), 1)
    structure_score = sum(float(item.get("structure_score", 0.0)) for item in group) / max(len(group), 1)
    final_field_score = (
        0.45 * _clamp(token_consensus_score)
        + 0.30 * _clamp(cross_image_agreement)
        + 0.25 * _clamp(region_spatial_confidence)
    )

    return {
        "token_consensus_score": round(_clamp(token_consensus_score), 4),
        "cross_image_agreement": round(_clamp(cross_image_agreement), 4),
        "region_spatial_confidence": round(_clamp(region_spatial_confidence), 4),
        "structure_score": round(_clamp(structure_score), 4),
        "region_weight_contribution": round(_clamp(region_spatial_confidence), 4),
        "final_field_score": round(_clamp(final_field_score), 4),
        "support_images": support_images,
        "support_ratio": round(support_images / total_images, 4),
    }


def _candidate_valid_for_field(field_name: str, value: str) -> bool:
    normalized = _normalize_for_field(field_name, value)
    if not normalized:
        return False
    if field_name == "batch_number":
        return _is_valid_batch_value(normalized)
    if field_name == "expiry_date":
        return bool(
            _RE_EXPIRY_STRICT.search(value)
            or re.fullmatch(r"\d{1,2}[/-]\d{2,4}", normalized)
            or re.fullmatch(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", normalized)
            or re.fullmatch(r"\d{4}", normalized)
            or re.search(r"\d{1,2}[/-]\d{2,4}", normalized)
        )
    if field_name == "mfg_date":
        return bool(
            _RE_MFG_STRICT.search(value)
            or re.fullmatch(r"\d{1,2}[/-]\d{2,4}", normalized)
            or re.fullmatch(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", normalized)
            or re.fullmatch(r"\d{4}", normalized)
            or re.search(r"\d{1,2}[/-]\d{2,4}", normalized)
        )
    if field_name == "manufacturer":
        return _is_valid_manufacturer_value(normalized)
    if field_name == "medicine_name":
        return not any(hint in normalized.lower() for hint in ("batch", "exp", "mfg", "manufact"))
    return True


def _candidate_recovery_reason(field_name: str, candidate_bucket: list[dict[str, Any]]) -> str:
    if not candidate_bucket:
        return "NO_VALID_CANDIDATES"
    valid_candidates = [
        item for item in candidate_bucket if _candidate_valid_for_field(field_name, str(item.get("token", "")))
    ]
    if not valid_candidates:
        return "FORMAT_INVALID"

    distinct_values = {
        _normalize_for_field(field_name, str(item.get("token", "")))
        for item in valid_candidates
        if _normalize_for_field(field_name, str(item.get("token", "")))
    }
    if max(float(item.get("structure_score", 0.0)) for item in valid_candidates) < 0.35:
        return "INSUFFICIENT_ALIGNMENT"
    if max(float(item.get("score", 0.0)) for item in valid_candidates) < 0.45:
        return "LOW_CROSS_IMAGE_SUPPORT"
    if len(distinct_values) > 1:
        if any(float(item.get("score", 0.0)) >= 0.65 for item in valid_candidates):
            return "CROSS_CONFLICT_BLOCKED"
        return "CONFLICTING_LAYOUT"
    return "WEAK_SIGNAL_REJECTED"


def _reconstruct_structured_value(field_name: str, value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""

    normalized = _normalize_for_field(field_name, text)
    if field_name == "batch_number":
        return normalized.upper()

    if field_name in {"expiry_date", "mfg_date"}:
        normalized = re.sub(r"\s+", "", normalized)
        normalized = re.sub(r"^(?:exp(?:iry)?|mfg|mfd|useby|usebefore|bestbefore|mandate|manufdate)\s*[:\-]?", "", normalized, flags=re.IGNORECASE)
        normalized = normalized.replace(".", "/")
        normalized = re.sub(r"(\d{1,2})(\d{2,4})$", r"\1/\2", normalized)
        normalized = re.sub(r"(\d{1,2})\s*[/-]\s*(\d{2,4})", r"\1/\2", normalized)
        normalized = re.sub(r"(\d{1,2})\s+(\d{2,4})", r"\1/\2", normalized)
        if field_name == "expiry_date":
            if _parse_strict_date(normalized):
                return normalized
            if re.fullmatch(r"\d{4}", normalized):
                return normalized
        else:
            if _parse_strict_date(normalized):
                return normalized
            if re.fullmatch(r"\d{4}", normalized):
                return normalized
        return normalized

    if field_name == "manufacturer":
        normalized = re.sub(r"^(?:manufacturer|mfr|by)\s*[:\-]?\s*", "", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized.title()

    if field_name == "medicine_name":
        normalized = re.sub(r"^(?:medicine|name)\s*[:\-]?\s*", "", normalized, flags=re.IGNORECASE)
        return normalized.strip().title()

    return normalized


def _reconstruct_structured_fields(fields: MedicineFields, raw_text: str) -> MedicineFields:
    reconstructed = MedicineFields(**asdict(fields))
    if hasattr(fields, "_fusion_weight_breakdown"):
        reconstructed._fusion_weight_breakdown = getattr(fields, "_fusion_weight_breakdown")  # type: ignore[attr-defined]
    for field_name in CORE_FIELD_NAMES:
        current_value = getattr(reconstructed, field_name, "")
        if not current_value:
            continue
        setattr(reconstructed, field_name, _reconstruct_structured_value(field_name, current_value))
    reconstructed.raw_text = raw_text
    return reconstructed


def _date_recovery_score(item: dict[str, Any], field_name: str) -> tuple[float, dict[str, float]]:
    token = str(item.get("token", ""))
    line_text = str(item.get("line_text", ""))
    normalized = _normalize_for_field(field_name, token)
    if field_name == "expiry_date":
        regex_score = 1.0 if (
            _RE_EXPIRY_STRICT.search(token)
            or re.fullmatch(r"\d{1,2}[/-]\d{2,4}", normalized)
            or re.fullmatch(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", normalized)
            or re.search(r"\d{4}", normalized)
        ) else 0.0
        keyword_score = 1.0 if any(keyword in line_text.lower() for keyword in ("exp", "expiry", "best before", "use by", "use before")) else 0.0
    else:
        regex_score = 1.0 if (
            _RE_MFG_STRICT.search(token)
            or re.fullmatch(r"\d{1,2}[/-]\d{2,4}", normalized)
            or re.fullmatch(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", normalized)
            or re.search(r"\d{4}", normalized)
        ) else 0.0
        keyword_score = 1.0 if any(keyword in line_text.lower() for keyword in ("mfg", "mfd", "manufactured", "manufacture", "manuf date")) else 0.0
    region_score = min(
        1.0,
        float(item.get("spatial_score", 0.0))
        + _fusion_region_bonus(field_name, str(item.get("region_origin", "full")), token, line_text),
    )
    final_score = round(0.5 * regex_score + 0.3 * keyword_score + 0.2 * region_score, 4)
    return final_score, {
        "regex_match_score": round(regex_score, 4),
        "keyword_proximity_score": round(keyword_score, 4),
        "region_spatial_score": round(region_score, 4),
    }


def _manufacturer_recovery_score(item: dict[str, Any]) -> tuple[float, dict[str, float]]:
    token = str(item.get("token", ""))
    line_text = str(item.get("line_text", ""))
    normalized = _normalize_for_field("manufacturer", token)
    lexical = 1.0 if _is_valid_manufacturer_value(normalized) else 0.0
    heuristic = 0.0
    lower = normalized.lower()
    if any(lower.endswith(suffix) for suffix in ("pharma", "labs", "industries", "care", "med")):
        heuristic += 0.35
    if re.fullmatch(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+", token.strip()):
        heuristic += 0.25
    if any(hint in line_text.lower() for hint in ("ltd", "limited", "pharma", "labs", "healthcare", "company", "corp", "inc", "pvt")):
        heuristic += 0.20
    region_score = min(
        1.0,
        float(item.get("spatial_score", 0.0))
        + _fusion_region_bonus("manufacturer", str(item.get("region_origin", "full")), token, line_text),
    )
    token_strength = min(1.0, float(item.get("score", 0.0)))
    soft_consensus_score = round(
        0.6 * min(1.0, token_strength)
        + 0.2 * region_score
        + 0.2 * min(1.0, lexical + heuristic),
        4,
    )
    return soft_consensus_score, {
        "lexical_score": round(min(1.0, lexical + heuristic), 4),
        "region_spatial_score": round(region_score, 4),
        "token_strength": round(min(1.0, token_strength), 4),
    }


def _resolve_global_medicine_name(
    image_pools: list[dict[str, list[dict[str, Any]]]],
    image_weights: list[float],
) -> tuple[str, list[dict[str, Any]], list[list[dict[str, Any]]], dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for image_index, pools in enumerate(image_pools):
        for item in pools.get("medicine_name", []):
            token = str(item.get("token", "")).strip()
            normalized = _normalize_for_field("medicine_name", token)
            if not normalized:
                continue
            candidates.append(
                {
                    "token": token,
                    "normalized": normalized,
                    "score": float(item.get("score", 0.0)),
                    "lexical_score": float(item.get("lexical_score", item.get("score", 0.0)) or 0.0),
                    "spatial_score": float(item.get("spatial_score", 0.0) or 0.0),
                    "line_index": int(item.get("line_index", 0) or 0),
                    "line_text": str(item.get("line_text", "")),
                    "region_origin": str(item.get("region_origin", "full")),
                    "image_index": image_index,
                    "image_weight": max(float(image_weights[image_index]), 0.01),
                }
            )

    if not candidates:
        return "", [], [], _fusion_score_components("medicine_name", [], len(image_pools))

    clusters = _cluster_medicine_candidates(candidates)
    ranked_clusters = []
    for cluster in clusters:
        breakdown = _fusion_score_components("medicine_name", cluster, len(image_pools))
        support_images = breakdown["support_images"]
        support_weight = sum(item["score"] * item["image_weight"] for item in cluster)
        total_score = sum(item["score"] for item in cluster)
        max_score = max((item["score"] for item in cluster), default=0.0)
        ranked_clusters.append(
            (
                breakdown["final_field_score"],
                breakdown["structure_score"],
                support_images,
                support_weight,
                total_score,
                max_score,
                breakdown,
                cluster,
            )
        )

    ranked_clusters.sort(key=lambda item: (item[0], item[1], item[2], item[3], item[4], item[5]), reverse=True)
    _, _, support_images, _, _, _, best_breakdown, best_cluster = ranked_clusters[0]
    canonical = Counter(item["normalized"] for item in best_cluster).most_common(1)[0][0]
    competing_strong = any(
        item[2] >= 2 and item[0] >= max(0.0, best_breakdown.get("final_field_score", 0.0) - 0.06)
        for item in ranked_clusters[1:]
    )
    if support_images >= 2 and not competing_strong:
        return canonical, candidates, clusters, best_breakdown

    return "", candidates, clusters, best_breakdown


def _resolve_field_from_global_candidates(
    field_name: str,
    image_pools: list[dict[str, list[dict[str, Any]]]],
    image_weights: list[float],
    *,
    identity: str = "",
    require_identity: bool = False,
) -> tuple[str, list[dict[str, Any]], set[str], dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for image_index, pools in enumerate(image_pools):
        if require_identity and not _image_supports_identity(pools, identity):
            continue
        for item in pools.get(field_name, []):
            token = str(item.get("token", "")).strip()
            normalized = _normalize_for_field(field_name, token)
            if not normalized:
                continue
            candidates.append(
                {
                    "token": token,
                    "normalized": normalized,
                    "score": float(item.get("score", 0.0)),
                    "lexical_score": float(item.get("lexical_score", item.get("score", 0.0)) or 0.0),
                    "spatial_score": float(item.get("spatial_score", 0.0) or 0.0),
                    "line_index": int(item.get("line_index", 0) or 0),
                    "line_text": str(item.get("line_text", "")),
                    "region_origin": str(item.get("region_origin", "full")),
                    "image_index": image_index,
                    "image_weight": max(float(image_weights[image_index]), 0.01),
                }
            )

    if not candidates:
        return "", candidates, set(), _fusion_score_components(field_name, [], len(image_pools))

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in candidates:
        grouped.setdefault(item["normalized"], []).append(item)

    if field_name == "manufacturer":
        clustered_groups = _cluster_manufacturer_candidates(candidates)
        grouped = {
            Counter(item["normalized"] for item in cluster).most_common(1)[0][0]: cluster
            for cluster in clustered_groups
        }

    ranked_groups = []
    for normalized, group in grouped.items():
        breakdown = _fusion_score_components(field_name, group, len(image_pools))
        support_images = breakdown["support_images"]
        support_weight = sum(item["score"] * item["image_weight"] for item in group)
        total_score = sum(item["score"] for item in group)
        max_score = max((item["score"] for item in group), default=0.0)
        ranked_groups.append((breakdown["final_field_score"], breakdown["structure_score"], support_images, support_weight, total_score, max_score, normalized, breakdown, group))

    ranked_groups.sort(key=lambda item: (item[0], item[1], item[2], item[3], item[4], item[5]), reverse=True)
    _, _, support_images, _, _, _, winner, best_breakdown, winning_group = ranked_groups[0]
    recovery_fields = {"expiry_date", "mfg_date", "manufacturer"}
    needs_recovery = field_name in recovery_fields and (
        support_images < 2
        or (field_name in {"expiry_date", "mfg_date"} and not _parse_strict_date(winner))
        or (field_name == "manufacturer" and not _is_valid_manufacturer_value(winner))
    )

    if support_images < 2 and field_name not in recovery_fields:
        return "", candidates, set(grouped), best_breakdown

    if needs_recovery:
        recovery_ranked: list[tuple[float, int, str, dict[str, Any], list[dict[str, Any]]]] = []
        for normalized, group in grouped.items():
            group_breakdown = _fusion_score_components(field_name, group, len(image_pools))
            best_item = max(
                group,
                key=lambda item: (
                    float(item.get("score", 0.0)),
                    float(item.get("image_weight", 0.0)),
                    -int(item.get("line_index", 0) or 0),
                ),
            )
            if field_name in {"expiry_date", "mfg_date"}:
                recovery_score, recovery_components = _date_recovery_score(best_item, field_name)
            else:
                recovery_score, recovery_components = _manufacturer_recovery_score(best_item)

            soft_score = (
                0.6 * float(group_breakdown.get("cross_image_agreement", 0.0))
                + 0.2 * float(group_breakdown.get("region_spatial_confidence", 0.0))
                + 0.2 * float(group_breakdown.get("token_consensus_score", 0.0))
            )
            combined_score = max(
                float(group_breakdown.get("final_field_score", 0.0)),
                soft_score,
                recovery_score,
                float(group_breakdown.get("structure_score", 0.0)) * 0.6,
            )
            if field_name == "manufacturer":
                combined_score = max(combined_score, min(1.0, recovery_score + 0.05))
            recovery_ranked.append((combined_score, len({item["image_index"] for item in group}), normalized, {**group_breakdown, **recovery_components, "recovery_score": round(recovery_score, 4), "soft_consensus_score": round(soft_score, 4)}, group))

        recovery_ranked.sort(key=lambda item: (item[0], item[1], len(item[4])), reverse=True)
        best_recovery_score, recovery_support_images, winner, recovery_breakdown, winning_group = recovery_ranked[0]
        conflicting_strong = [
            item for item in recovery_ranked[1:]
            if item[0] >= 0.65
        ]
        if len(conflicting_strong) >= 2:
            return "", candidates, set(grouped), {**recovery_breakdown, "blocked_reason": "CROSS_CONFLICT_BLOCKED"}

        if field_name in {"expiry_date", "mfg_date"}:
            if recovery_support_images >= 2 and best_recovery_score >= 0.65:
                if not _parse_strict_date(winner):
                    return "", candidates, set(grouped), {**recovery_breakdown, "blocked_reason": "FORMAT_INVALID"}
                return winner, candidates, set(grouped), {**recovery_breakdown, "recovery_mode": True}
            return "", candidates, set(grouped), {**recovery_breakdown, "blocked_reason": "WEAK_SIGNAL_REJECTED"}

        if field_name == "manufacturer":
            competing_manufacturer = any(
                item[1] >= 2 and item[0] >= max(0.0, best_recovery_score - 0.07)
                for item in recovery_ranked[1:]
            )
            if recovery_support_images >= 2 and best_recovery_score >= 0.48 and not competing_manufacturer:
                if not _is_plausible_manufacturer_value(winner):
                    return "", candidates, set(grouped), {**recovery_breakdown, "blocked_reason": "FORMAT_INVALID"}
                return winner, candidates, set(grouped), {**recovery_breakdown, "recovery_mode": True}
            return "", candidates, set(grouped), {**recovery_breakdown, "blocked_reason": "WEAK_SIGNAL_REJECTED"}

    if field_name in {"expiry_date", "mfg_date"} and not _parse_strict_date(winner):
        return "", candidates, set(grouped), best_breakdown
    if field_name == "batch_number" and not _is_valid_batch_value(winner):
        return "", candidates, set(grouped), best_breakdown
    if field_name == "manufacturer" and not _is_valid_manufacturer_value(winner):
        return "", candidates, set(grouped), best_breakdown
    if field_name == "medicine_name" and any(hint in winner.lower() for hint in ("batch", "exp", "mfg", "manufact", "tablet", "capsule")):
        return "", candidates, set(grouped), best_breakdown

    return winner, candidates, set(grouped), best_breakdown


def _soft_field_decision(
    field_name: str,
    image_pools: list[dict[str, list[dict[str, Any]]]],
    image_weights: list[float],
) -> dict[str, Any]:
    if field_name not in {"medicine_name", "manufacturer"}:
        return {
            "value": "",
            "state": "REJECTED",
            "confidence_score": 0.0,
            "reason": "NO_VALID_CANDIDATES",
            "evidence_sources": [],
            "breakdown": _fusion_score_components(field_name, [], len(image_pools)),
        }

    candidates: list[dict[str, Any]] = []
    for image_index, pools in enumerate(image_pools):
        for item in pools.get(field_name, []):
            token = str(item.get("token", "")).strip()
            normalized = _normalize_for_field(field_name, token)
            if not normalized:
                continue
            candidates.append(
                {
                    "token": token,
                    "normalized": normalized,
                    "score": float(item.get("score", 0.0)),
                    "lexical_score": float(item.get("lexical_score", item.get("score", 0.0)) or 0.0),
                    "spatial_score": float(item.get("spatial_score", 0.0) or 0.0),
                    "structure_score": float(item.get("structure_score", 0.0) or 0.0),
                    "line_index": int(item.get("line_index", 0) or 0),
                    "line_text": str(item.get("line_text", "")),
                    "region_origin": str(item.get("region_origin", "full")),
                    "image_index": image_index,
                    "image_weight": max(float(image_weights[image_index]), 0.01),
                }
            )

    if not candidates:
        return {
            "value": "",
            "state": "REJECTED",
            "confidence_score": 0.0,
            "reason": "NO_VALID_CANDIDATES",
            "evidence_sources": [],
            "breakdown": _fusion_score_components(field_name, [], len(image_pools)),
        }

    total_noise = sum(len(pools.get("noise", [])) for pools in image_pools)
    total_signal = sum(len(pools.get(field_name, [])) for pools in image_pools)
    noise_ratio = total_noise / max(total_signal + total_noise, 1)

    clusters = _cluster_medicine_candidates(candidates) if field_name == "medicine_name" else _cluster_manufacturer_candidates(candidates)
    ranked_clusters: list[dict[str, Any]] = []
    for cluster in clusters:
        breakdown = _fusion_score_components(field_name, cluster, len(image_pools))
        signal_sources = {
            "cross_image": breakdown["support_images"] >= 2,
            "repetition": len({item["normalized"] for item in cluster}) == 1 and breakdown["support_images"] >= 2,
            "structure": max((float(item.get("structure_score", 0.0)) for item in cluster), default=0.0) >= 0.15,
            "region": max((float(item.get("region_alignment_score", 0.0)) for item in cluster), default=0.0) >= 0.20
            or max((float(item.get("spatial_score", 0.0)) for item in cluster), default=0.0) >= 0.20,
            "format": all(
                _is_plausible_medicine_name(item["normalized"], cluster)
                if field_name == "medicine_name"
                else _is_plausible_manufacturer_value(item["normalized"])
                for item in cluster
            ),
        }
        best_item = max(
            cluster,
            key=lambda item: (
                float(item.get("score", 0.0)),
                float(item.get("structure_score", 0.0)),
                float(item.get("spatial_score", 0.0)),
                -int(item.get("line_index", 0) or 0),
                len(str(item.get("token", ""))),
            ),
        )
        ranked_clusters.append(
            {
                "value": str(best_item.get("token", "")).strip(),
                "normalized": str(best_item.get("normalized", "")).strip(),
                "score": float(breakdown.get("final_field_score", 0.0)),
                "support_images": int(breakdown.get("support_images", 0)),
                "structure_score": float(breakdown.get("structure_score", 0.0)),
                "region_spatial_confidence": float(breakdown.get("region_spatial_confidence", 0.0)),
                "signal_sources": signal_sources,
                "breakdown": breakdown,
                "cluster": cluster,
            }
        )

    ranked_clusters.sort(
        key=lambda item: (
            item["score"],
            item["support_images"],
            item["structure_score"],
            item["region_spatial_confidence"],
            len(item["cluster"]),
        ),
        reverse=True,
    )
    best = ranked_clusters[0]
    competing_strong = any(
        item["support_images"] >= 2 and item["score"] >= max(0.0, best["score"] - 0.07)
        for item in ranked_clusters[1:]
    )
    best_signals = best["signal_sources"]
    independent_signal_count = sum(1 for key, present in best_signals.items() if present)
    noise_class = "NOISE" if noise_ratio >= 0.45 or (best["score"] < 0.55 and independent_signal_count < 2) else "CLEAN"

    if field_name == "medicine_name":
        plausible = _is_plausible_medicine_name(best["value"], best["cluster"])
        confirmed = (
            best["score"] >= 0.80
            and best["support_images"] >= 2
            and independent_signal_count >= 2
            and not competing_strong
            and plausible
        )
    else:
        plausible = _is_plausible_manufacturer_value(best["value"])
        confirmed = (
            best["score"] >= 0.80
            and best["support_images"] >= 2
            and independent_signal_count >= 2
            and not competing_strong
            and plausible
        )

    if confirmed:
        return {
            "value": best["value"],
            "state": "CONFIRMED",
            "confidence_score": round(min(1.0, best["score"]), 4),
            "reason": "",
            "evidence_sources": [
                {
                    "image_id": item["image_index"],
                    "token": item["token"],
                    "origin": item["region_origin"],
                    "source": item.get("source", "token"),
                }
                for item in best["cluster"]
            ],
            "breakdown": best["breakdown"],
        }
    rejection_reason = "CROSS_CONFLICT_BLOCKED" if competing_strong else "WEAK_SIGNAL_REJECTED"
    if noise_class == "NOISE":
        rejection_reason = "NOISE"
    if best["support_images"] < 2:
        rejection_reason = "NOISE" if noise_ratio >= 0.45 else "WEAK_SIGNAL_REJECTED"
    if independent_signal_count < 2:
        rejection_reason = "WEAK_SIGNAL_REJECTED"
    if not plausible:
        rejection_reason = "FORMAT_INVALID"
    return {
        "value": "",
        "state": "REJECTED",
        "confidence_score": round(min(1.0, best["score"]), 4),
        "reason": rejection_reason,
        "evidence_sources": [
            {
                "image_id": item["image_index"],
                "token": item["token"],
                "origin": item["region_origin"],
                "source": item.get("source", "token"),
            }
            for item in best["cluster"]
        ],
        "breakdown": best["breakdown"],
    }


def _best_single_candidate(
    values: list[str],
    scores: list[float],
    field_name: str,
) -> tuple[str, float]:
    best_value = ""
    best_score = 0.0
    for value, score in zip(values, scores):
        normalized = _normalize_for_field(field_name, value)
        if not normalized:
            continue
        if field_name == "batch_number" and not _is_valid_batch_value(normalized):
            continue
        if field_name in {"expiry_date", "mfg_date"} and not _parse_strict_date(normalized):
            continue
        if field_name == "manufacturer" and not _is_valid_manufacturer_value(normalized):
            continue
        if field_name == "medicine_name" and any(hint in normalized.lower() for hint in ("batch", "exp", "mfg", "manufact")):
            continue
        if score > best_score:
            best_score = score
            best_value = normalized
    return best_value, round(best_score, 4)


def _recover_date_candidate(
    values: list[str],
    scores: list[float],
    field_name: str,
) -> tuple[str, float]:
    best_value = ""
    best_score = 0.0
    for value, score in zip(values, scores):
        normalized = _normalize_for_field(field_name, value)
        if not normalized:
            continue
        if field_name == "expiry_date":
            acceptable = bool(
                _RE_EXPIRY_STRICT.search(value)
                or re.search(r"\d{1,2}[/-]\d{2,4}", normalized)
                or re.search(r"\d{2}[/-]\d{4}", normalized)
            )
        else:
            acceptable = bool(
                _RE_MFG_STRICT.search(value)
                or re.search(r"\d{1,2}[/-]\d{2,4}", normalized)
                or re.search(r"\d{2}[/-]\d{4}", normalized)
            )
        if not acceptable:
            continue
        if score > best_score:
            best_score = score
            best_value = normalized
    return best_value, round(best_score, 4)


def _field_empty_reason(
    field_name: str,
    final_value: str,
    candidate_bucket: list[dict[str, Any]],
    raw_text: str,
) -> str:
    if final_value:
        return ""
    if not (raw_text or "").strip():
        return "NO_TEXT_DETECTED"
    if not candidate_bucket:
        return "NO_VALID_CANDIDATES"
    reason = _candidate_recovery_reason(field_name, candidate_bucket)
    return reason


def _build_field_evidence(
    raw_text: str,
    per_image: list[MedicineFields],
    final_fields: MedicineFields,
    derived: DerivedParameters | None = None,
) -> dict[str, dict[str, Any]]:
    pools = _build_token_pools(raw_text)
    evidence: dict[str, dict[str, Any]] = {}

    for field_name in CORE_FIELD_NAMES:
        final_value = _normalize_for_field(field_name, getattr(final_fields, field_name))
        candidate_bucket = pools.get(field_name, [])
        candidate_count = len(candidate_bucket)
        best_score = round(max((float(item.get("score", 0.0)) for item in candidate_bucket), default=0.0), 4)
        candidate_values = [str(item.get("token", "")).strip() for item in candidate_bucket if str(item.get("token", "")).strip()]
        normalized_values = { _normalize_for_field(field_name, value) for value in candidate_values if _normalize_for_field(field_name, value) }
        per_image_values = [
            _normalize_for_field(field_name, getattr(image, field_name))
            for image in per_image
            if _normalize_for_field(field_name, getattr(image, field_name))
        ]
        distinct_values = set(per_image_values) | normalized_values
        signal_exists = bool(candidate_count or distinct_values)

        if candidate_bucket:
            best_candidate = max(
                candidate_bucket,
                key=lambda item: (float(item.get("score", 0.0)), -int(item.get("line_index", 0) or 0), len(str(item.get("token", "")))),
            )
            region_origin = str(best_candidate.get("region_origin", "full"))
            spatial_confidence = round(float(best_candidate.get("spatial_score", 0.0)), 4)
            structure_origin = str(best_candidate.get("source", "token"))
            line_support_count = len({int(item.get("line_index", 0) or 0) for item in candidate_bucket})
            region_support_count = sum(
                1
                for item in candidate_bucket
                if str(item.get("region_origin", "full")) == region_origin
                and float(item.get("score", 0.0)) >= max(0.35, best_score * 0.6)
            )
        else:
            region_origin = "none"
            spatial_confidence = 0.0
            structure_origin = "none"
            line_support_count = 0
            region_support_count = 0
        fusion_breakdown = getattr(final_fields, "_fusion_weight_breakdown", {}).get(field_name, {})

        empty_reason = _field_empty_reason(
            field_name,
            final_value,
            candidate_bucket,
            raw_text,
        )
        rejection_reason = empty_reason or ""
        if final_value:
            field_state = "RESOLVED"
            rejection_reason = ""
        elif empty_reason == "NO_TEXT_DETECTED":
            field_state = "NO_STRUCTURE_SIGNAL"
        elif empty_reason == "NO_VALID_CANDIDATES":
            field_state = "NO_VALID_CANDIDATES"
        elif empty_reason == "FORMAT_INVALID":
            field_state = "LOW_CONFIDENCE"
        elif empty_reason in {"CROSS_CONFLICT_BLOCKED", "CONFLICTING_LAYOUT"}:
            field_state = "CONFLICTED"
        elif empty_reason in {"WEAK_SIGNAL_REJECTED", "LOW_CROSS_IMAGE_SUPPORT", "INSUFFICIENT_ALIGNMENT"}:
            field_state = "LOW_CONFIDENCE"
        else:
            field_state = "NO_VALID_CANDIDATES"
        if candidate_count == 0:
            rejection_reason = "NO_VALID_CANDIDATES"
        elif not final_value and not rejection_reason:
            rejection_reason = empty_reason or "WEAK_SIGNAL_REJECTED"

        recovery_attempts = 1 if candidate_count or signal_exists else 0
        evidence[field_name] = {
            "field_state": field_state,
            "signal_exists": signal_exists,
            "empty_reason": empty_reason,
            "candidate_count": candidate_count,
            "best_score": best_score,
            "region_origin": region_origin,
            "structure_origin": structure_origin,
            "spatial_confidence": spatial_confidence,
            "line_support_count": line_support_count,
            "region_support_count": region_support_count,
            "line_alignment_score": round(float(fusion_breakdown.get("line_alignment_score", 0.0)), 4) if fusion_breakdown else 0.0,
            "region_alignment_score": round(float(fusion_breakdown.get("region_alignment_score", 0.0)), 4) if fusion_breakdown else 0.0,
            "keyword_proximity_score": round(float(fusion_breakdown.get("keyword_proximity_score", 0.0)), 4) if fusion_breakdown else 0.0,
            "structure_score": round(float(fusion_breakdown.get("structure_score", 0.0)), 4) if fusion_breakdown else 0.0,
            "region_score": round(float(fusion_breakdown.get("region_spatial_confidence", spatial_confidence)), 4) if fusion_breakdown else spatial_confidence,
            "cross_image_score": round(float(fusion_breakdown.get("cross_image_agreement", 0.0)), 4) if fusion_breakdown else 0.0,
            "final_score": round(float(fusion_breakdown.get("final_field_score", 0.0)), 4) if fusion_breakdown else 0.0,
            "fusion_weight_breakdown": fusion_breakdown,
            "region_weight_contribution": round(float(fusion_breakdown.get("region_weight_contribution", spatial_confidence)) if fusion_breakdown else spatial_confidence, 4),
            "final_score_components": {
                "token_consensus_score": round(float(fusion_breakdown.get("token_consensus_score", 0.0)), 4) if fusion_breakdown else 0.0,
                "cross_image_agreement": round(float(fusion_breakdown.get("cross_image_agreement", 0.0)), 4) if fusion_breakdown else 0.0,
                "region_spatial_confidence": round(float(fusion_breakdown.get("region_spatial_confidence", spatial_confidence)), 4) if fusion_breakdown else spatial_confidence,
                "structure_score": round(float(fusion_breakdown.get("structure_score", 0.0)), 4) if fusion_breakdown else 0.0,
                "final_field_score": round(float(fusion_breakdown.get("final_field_score", 0.0)), 4) if fusion_breakdown else 0.0,
            },
            "reconstruction_applied": bool(final_value),
            "recovery_attempts": recovery_attempts,
            "rejection_reason": rejection_reason,
            "candidate_values": candidate_values[:10],
        }

    return evidence


def _build_field_decisions(
    final_fields: MedicineFields,
    per_image_results: list[MedicineFields],
    evidence: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    decisions: dict[str, dict[str, Any]] = {}
    for field_name in CORE_FIELD_NAMES:
        field_value = getattr(final_fields, field_name).strip()
        field_evidence = evidence.get(field_name, {})
        state = "CONFIRMED" if field_value else "REJECTED"
        confidence_score = float(
            field_evidence.get(
                "confidence_score",
                field_evidence.get("final_score", field_evidence.get("best_score", 0.0)),
            )
            or 0.0
        )
        if not field_value:
            confidence_score = 0.0

        evidence_sources: list[dict[str, Any]] = []
        for image_index, image in enumerate(per_image_results):
            image_value = _normalize_for_field(field_name, getattr(image, field_name))
            if field_value and image_value == _normalize_for_field(field_name, field_value):
                evidence_sources.append(
                    {
                        "image_id": image_index,
                        "token": getattr(image, field_name),
                        "origin": field_evidence.get("region_origin", "unknown"),
                    }
                )

        if not evidence_sources:
            for token in field_evidence.get("candidate_values", [])[:3]:
                evidence_sources.append(
                    {
                        "image_id": -1,
                        "token": token,
                        "origin": field_evidence.get("region_origin", "unknown"),
                    }
                )

        signal_breakdown = {
            "signal_availability": {
                "has_candidate_values": bool(field_evidence.get("candidate_values")),
                "has_cross_image_support": float(field_evidence.get("cross_image_score", 0.0) or 0.0) >= 0.5,
                "has_region_support": float(field_evidence.get("region_score", 0.0) or 0.0) >= 0.4,
                "has_structure_support": float(field_evidence.get("structure_score", 0.0) or 0.0) > 0.0,
                "has_noise_pressure": float(field_evidence.get("noise_ratio", 0.0) or 0.0) >= 0.45,
                "has_semantic_variance": False,
            },
            "candidate_count": int(field_evidence.get("candidate_count", 0) or 0),
            "best_score": round(float(field_evidence.get("best_score", 0.0) or 0.0), 4),
            "region_origin": field_evidence.get("region_origin", "unknown"),
            "structure_origin": field_evidence.get("structure_origin", "unknown"),
            "cross_image_score": round(float(field_evidence.get("cross_image_score", 0.0) or 0.0), 4),
            "region_score": round(float(field_evidence.get("region_score", 0.0) or 0.0), 4),
            "region_alignment_score": round(float(field_evidence.get("region_score", 0.0) or 0.0), 4),
            "structure_score": round(float(field_evidence.get("structure_score", 0.0) or 0.0), 4),
            "noise_score": round(float(field_evidence.get("noise_ratio", 0.0) or 0.0), 4),
            "cross_image_support_score": round(float(field_evidence.get("cross_image_score", 0.0) or 0.0), 4),
            "format_validity_score": 1.0 if not field_evidence.get("rejection_reason") or field_evidence.get("rejection_reason") != "FORMAT_INVALID" else 0.0,
            "conflict_score": 1.0 if field_evidence.get("rejection_reason") in {"CROSS_CONFLICT_BLOCKED", "EVIDENCE_CONTRADICTION"} else 0.0,
            "semantic_variance_score": round(_semantic_variance_score([getattr(image, field_name) for image in per_image_results], field_name), 4),
            "final_score": round(float(field_evidence.get("final_score", 0.0) or 0.0), 4),
            "final_score_components": dict(field_evidence.get("final_score_components", {}) or {}),
        }
        signal_breakdown["consistency_stress_score"] = round(
            max(
                float(signal_breakdown.get("conflict_score", 0.0) or 0.0),
                float(signal_breakdown.get("semantic_variance_score", 0.0) or 0.0),
            ),
            4,
        )
        signal_breakdown["signal_availability"]["has_semantic_variance"] = bool(signal_breakdown["semantic_variance_score"] > 0.0)
        signal_breakdown["calibrated_confidence"] = round(
            0.35 * float(signal_breakdown.get("cross_image_support_score", 0.0) or 0.0)
            + 0.25 * float(signal_breakdown.get("format_validity_score", 0.0) or 0.0)
            + 0.20 * float(signal_breakdown.get("region_alignment_score", 0.0) or 0.0)
            + 0.20 * (1.0 - float(signal_breakdown.get("noise_score", 0.0) or 0.0)),
            4,
        )
        signal_breakdown["decision_state"] = "CONFIRMED" if state == "CONFIRMED" else "WEAK_CONFIRMED"

        rejection_reason = "" if state == "CONFIRMED" else field_evidence.get("rejection_reason", "") or field_evidence.get("empty_reason", "") or "WEAK_SIGNAL_REJECTED"
        failure_mode = _consolidated_failure_mode(rejection_reason, signal_breakdown)

        decisions[field_name] = {
            "value": field_value,
            "state": state,
            "confidence_score": round(confidence_score, 4),
            "rejection_reason": rejection_reason,
            "failure_mode": failure_mode,
            "evidence_sources": evidence_sources,
            "signal_breakdown": signal_breakdown,
        }

    return decisions


def evidence_truth_validator(
    final_fields: MedicineFields,
    per_image_results: list[MedicineFields],
    evidence: dict[str, dict[str, Any]],
    field_decisions: dict[str, dict[str, Any]],
    raw_text: str,
) -> tuple[MedicineFields, dict[str, dict[str, Any]], dict[str, dict[str, bool]]]:
    validated_fields = MedicineFields(**asdict(final_fields))
    validated_decisions = {
        name: dict(decision)
        for name, decision in field_decisions.items()
    }
    validation_flags: dict[str, dict[str, bool]] = {}
    total_tokens = max(sum(len((img.raw_text or "").split()) for img in per_image_results), 1)
    noisy_tokens = sum(
        len(evidence.get(name, {}).get("candidate_values", []))
        for name in CORE_FIELD_NAMES
        if evidence.get(name, {}).get("rejection_reason") in {"NOISE", "WEAK_SIGNAL_REJECTED", "NOISE_DOMINANT", "LOW_OCR_CONFIDENCE"}
    )
    noise_ratio = noisy_tokens / total_tokens

    for field_name in CORE_FIELD_NAMES:
        decision = validated_decisions.get(field_name, {}) or {}
        field_evidence = evidence.get(field_name, {}) or {}
        field_value = str(decision.get("value", "") or "").strip()
        state = str(decision.get("state", "REJECTED") or "REJECTED").strip() or "REJECTED"
        evidence_sources = decision.get("evidence_sources", []) or []
        candidate_values = [str(value).strip() for value in field_evidence.get("candidate_values", []) if str(value).strip()]
        normalized_candidates = {_normalize_for_field(field_name, value) for value in candidate_values if _normalize_for_field(field_name, value)}
        per_image_values = [
            _normalize_for_field(field_name, getattr(image, field_name))
            for image in per_image_results
            if _normalize_for_field(field_name, getattr(image, field_name))
        ]
        support_images = len(set(per_image_values))
        has_contradiction = len(set(per_image_values) | normalized_candidates) > 1
        evidence_sufficient = (
            len(evidence_sources) >= 2
            or support_images >= 2
            or (len(evidence_sources) == 1 and field_evidence.get("structure_score", 0.0) >= 0.35)
        )
        no_contradiction = not has_contradiction
        cross_image_supported = support_images >= 2 or (support_images == 1 and field_evidence.get("structure_score", 0.0) >= 0.35)
        noise_within_limit = noise_ratio <= 0.4 and field_evidence.get("noise_class", "CLEAN") != "NOISE"
        semantic_variance_score = float(field_evidence.get("semantic_variance_score", 0.0) or 0.0)
        supporting_signal_count = sum(
            1
            for signal in (
                bool(evidence_sufficient),
                bool(no_contradiction),
                bool(cross_image_supported),
                bool(noise_within_limit),
                semantic_variance_score > 0.0,
            )
            if signal
        )

        if state == "CONFIRMED":
            direct_support = any(
                _normalize_for_field(field_name, src.get("token", "")) == _normalize_for_field(field_name, field_value)
                for src in evidence_sources
                if isinstance(src, dict)
            )
            if not (evidence_sufficient and no_contradiction and cross_image_supported and noise_within_limit and direct_support and supporting_signal_count >= 1):
                validated_decisions[field_name]["state"] = "REJECTED"
                validated_decisions[field_name]["value"] = ""
                validated_decisions[field_name]["rejection_reason"] = "EVIDENCE_CONTRADICTION" if has_contradiction else "WEAK_SIGNAL_REJECTED"
                validated_decisions[field_name]["failure_mode"] = _consolidated_failure_mode(
                    validated_decisions[field_name]["rejection_reason"],
                    validated_decisions[field_name].get("signal_breakdown", {}),
                )
                setattr(validated_fields, field_name, "")
            else:
                setattr(validated_fields, field_name, field_value)
        else:
            validated_decisions[field_name]["state"] = "REJECTED"
            if not validated_decisions[field_name].get("rejection_reason"):
                if noise_ratio > 0.4 or field_evidence.get("noise_class", "") == "NOISE":
                    validated_decisions[field_name]["rejection_reason"] = "NOISE_DOMINANT"
                elif has_contradiction:
                    validated_decisions[field_name]["rejection_reason"] = "EVIDENCE_CONTRADICTION"
                elif not candidate_values:
                    validated_decisions[field_name]["rejection_reason"] = "NO_VALID_CANDIDATES"
                else:
                    validated_decisions[field_name]["rejection_reason"] = "WEAK_SIGNAL_REJECTED"
            setattr(validated_fields, field_name, "")
            validated_decisions[field_name]["failure_mode"] = _consolidated_failure_mode(
                validated_decisions[field_name]["rejection_reason"],
                validated_decisions[field_name].get("signal_breakdown", {}),
            )

        validation_flags[field_name] = {
            "evidence_sufficient": bool(evidence_sufficient),
            "no_contradiction": bool(no_contradiction),
            "cross_image_supported": bool(cross_image_supported),
            "noise_within_limit": bool(noise_within_limit),
        }
        validated_decisions[field_name]["validation_flags"] = validation_flags[field_name]
        validated_decisions[field_name]["signal_breakdown"] = dict(validated_decisions[field_name].get("signal_breakdown", {}))
        validated_decisions[field_name]["signal_breakdown"]["semantic_variance_score"] = round(semantic_variance_score, 4)
        validated_decisions[field_name]["signal_breakdown"]["consistency_stress_score"] = round(
            max(
                float(validated_decisions[field_name]["signal_breakdown"].get("conflict_score", 0.0) or 0.0),
                semantic_variance_score,
            ),
            4,
        )
        validated_decisions[field_name]["signal_breakdown"]["calibrated_confidence"] = round(
            0.35 * float(validated_decisions[field_name]["signal_breakdown"].get("cross_image_support_score", validated_decisions[field_name]["signal_breakdown"].get("cross_image_agreement", 0.0)) or 0.0)
            + 0.25 * float(validated_decisions[field_name]["signal_breakdown"].get("format_validity_score", 0.0) or 0.0)
            + 0.20 * float(validated_decisions[field_name]["signal_breakdown"].get("region_alignment_score", validated_decisions[field_name]["signal_breakdown"].get("region_consistency_score", 0.0)) or 0.0)
            + 0.20 * (1.0 - float(validated_decisions[field_name]["signal_breakdown"].get("noise_score", validated_decisions[field_name]["signal_breakdown"].get("noise_ratio", 0.0)) or 0.0)),
            4,
        )
        validated_decisions[field_name]["signal_breakdown"]["decision_state"] = "CONFIRMED" if getattr(validated_fields, field_name).strip() else "WEAK_CONFIRMED"
        validated_decisions[field_name]["state"] = "CONFIRMED" if getattr(validated_fields, field_name).strip() else "REJECTED"
        validated_decisions[field_name]["confidence_score"] = round(
            float(validated_decisions[field_name].get("confidence_score", 0.0) or 0.0),
            4,
        )
        if validated_decisions[field_name]["state"] == "CONFIRMED" and supporting_signal_count < 1:
            validated_decisions[field_name]["state"] = "REJECTED"
            validated_decisions[field_name]["value"] = ""
            validated_decisions[field_name]["rejection_reason"] = "WEAK_SIGNAL_REJECTED"
            validated_decisions[field_name]["failure_mode"] = "INSUFFICIENT_EVIDENCE"
            setattr(validated_fields, field_name, "")
        elif validated_decisions[field_name]["state"] == "REJECTED":
            validated_decisions[field_name]["failure_mode"] = _consolidated_failure_mode(
                validated_decisions[field_name].get("rejection_reason", ""),
                validated_decisions[field_name].get("signal_breakdown", {}),
            )
        if not getattr(validated_fields, field_name).strip():
            validated_decisions[field_name]["value"] = ""
        if validated_decisions[field_name]["state"] == "REJECTED" and not validated_decisions[field_name].get("failure_mode"):
            validated_decisions[field_name]["failure_mode"] = "INSUFFICIENT_EVIDENCE"
        validated_decisions[field_name]["signal_breakdown"]["decision_state"] = validated_decisions[field_name]["state"]

    return validated_fields, validated_decisions, validation_flags


def fuse_results(per_image: list[MedicineFields]) -> tuple[MedicineFields, list[str], DerivedParameters]:
    """
    Combine per-image extraction results into one authoritative record.

    Algorithm per field:
        1. Collect all non-empty values + their confidence weights
        2. Use weighted majority vote
        3. If still ambiguous Ã¢â€ â€™ pick highest-confidence single value
        4. Record field-level conflicts

    Returns:
        (final_fields, conflicts, derived_params)
    """
    if not per_image:
        return MedicineFields(), [], DerivedParameters()

    weights = [img.confidence for img in per_image]
    # Avoid zero-weight edge case
    weights = [max(w, 0.01) for w in weights]
    image_pools = _collect_image_pools(per_image)

    conflicts: list[str] = []
    final = MedicineFields()
    conflict_fields: set[str] = set()
    fusion_weight_breakdown: dict[str, dict[str, Any]] = {}

    resolved_medicine_name, medicine_candidates, medicine_clusters, medicine_breakdown = _resolve_global_medicine_name(image_pools, weights)
    final.medicine_name = resolved_medicine_name
    fusion_weight_breakdown["medicine_name"] = medicine_breakdown

    medicine_distinct = sorted(
        {
            item["normalized"]
            for item in medicine_candidates
            if item["normalized"]
        }
    )
    if len(medicine_distinct) > 1:
        conflict_fields.add("medicine_name")
        conflicts.append(f"medicine_name mismatch: {medicine_distinct}")
    elif medicine_clusters and not resolved_medicine_name:
        conflict_fields.add("medicine_name")
        conflicts.append("medicine_name mismatch: insufficient cross-image consensus")

    batch_value, batch_candidates, _, batch_breakdown = _resolve_field_from_global_candidates(
        "batch_number",
        image_pools,
        weights,
        identity=resolved_medicine_name,
        require_identity=True,
    )
    expiry_value, expiry_candidates, _, expiry_breakdown = _resolve_field_from_global_candidates(
        "expiry_date",
        image_pools,
        weights,
    )
    mfg_value, mfg_candidates, _, mfg_breakdown = _resolve_field_from_global_candidates(
        "mfg_date",
        image_pools,
        weights,
    )
    manufacturer_value, manufacturer_candidates, _, manufacturer_breakdown = _resolve_field_from_global_candidates(
        "manufacturer",
        image_pools,
        weights,
    )

    final.batch_number = batch_value
    final.expiry_date = expiry_value
    final.mfg_date = mfg_value
    final.manufacturer = manufacturer_value

    fusion_weight_breakdown["batch_number"] = batch_breakdown
    fusion_weight_breakdown["expiry_date"] = expiry_breakdown
    fusion_weight_breakdown["mfg_date"] = mfg_breakdown
    fusion_weight_breakdown["manufacturer"] = manufacturer_breakdown

    field_candidate_map = {
        "batch_number": batch_candidates,
        "expiry_date": expiry_candidates,
        "mfg_date": mfg_candidates,
        "manufacturer": manufacturer_candidates,
    }
    for field_name, candidates in field_candidate_map.items():
        distinct = sorted({item["normalized"] for item in candidates if item["normalized"]})
        if len(distinct) > 1:
            conflict_fields.add(field_name)
            conflicts.append(f"{field_name} mismatch: {distinct}")

    qr_values = [getattr(img, "qr_data") for img in per_image]
    final.qr_data = _weighted_majority(qr_values, weights, "qr_data")
    qr_support = sum(
        1
        for value in qr_values
        if _normalize_for_field("qr_data", value) == _normalize_for_field("qr_data", final.qr_data) and final.qr_data
    )
    if len(per_image) > 1 and qr_support < 2:
        final.qr_data = ""
    qr_distinct = {
        _normalize_for_field("qr_data", v)
        for v in qr_values
        if _normalize_for_field("qr_data", v)
    }
    if len(qr_distinct) > 1:
        conflict_fields.add("qr_data")
        conflicts.append(f"qr_data mismatch: {sorted(qr_distinct)}")

    # Ã¢â€â‚¬Ã¢â€â‚¬ Derived parameters Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    total_fields = len(CORE_FIELD_NAMES)

    # agreement_score: average fraction of images agreeing with final value
    agreement_scores = []
    for field_name in CORE_FIELD_NAMES:
        final_val = getattr(final, field_name).strip()
        if not final_val:
            continue
        agree = sum(
            1 for img in per_image
            if _normalize_for_field(field_name, getattr(img, field_name)) == final_val
        )
        agreement_scores.append(agree / len(per_image))
    agreement_score = statistics.mean(agreement_scores) if agreement_scores else 0.0

    # consistency_score: batch + expiry + manufacturer must all agree
    consistency_fields = ["batch_number", "expiry_date", "manufacturer"]
    consistent = sum(1 for f in consistency_fields if f not in conflict_fields)
    consistency_score = consistent / len(consistency_fields)

    conflict_count = len(conflicts)

    # missing_field_ratio
    missing = sum(1 for f in CORE_FIELD_NAMES if not getattr(final, f).strip())
    missing_field_ratio = missing / total_fields

    # ocr_confidence: blend mean per-image confidence with agreement
    mean_conf = statistics.mean(weights) if weights else 0.0
    ocr_confidence = round(0.6 * mean_conf + 0.4 * agreement_score, 4)

    derived = DerivedParameters(
        agreement_score=round(agreement_score, 4),
        consistency_score=round(consistency_score, 4),
        conflict_count=conflict_count,
        missing_field_ratio=round(missing_field_ratio, 4),
        ocr_confidence=ocr_confidence,
    )

    final._fusion_weight_breakdown = fusion_weight_breakdown  # type: ignore[attr-defined]

    return final, conflicts, derived


# ---------------------------------------------------------------------------
# MAIN PIPELINE ENTRY POINT
# ---------------------------------------------------------------------------

def process_medicine_images(images: list) -> dict:
    """
    Full MediShield OCR pipeline.

    Args:
        images: List of image inputs (file paths, PIL Images, or numpy arrays).

    Returns:
        Structured dict matching the MediShield JSON schema.
    """
    if not images:
        logger.warning("No images provided.")
        return _empty_result()

    per_image_results: list[MedicineFields] = []
    all_raw_text: list[str] = []
    ocr_traces: list[dict[str, Any]] = []

    for idx, img_input in enumerate(images):
        logger.info(f"Processing image {idx + 1}/{len(images)} ...")

        try:
            raw_text, ocr_confidence = ocr_core(img_input)
            trace = dict(getattr(ocr_core, "last_trace", {}))
            ocr_traces.append(trace)
            logger.debug(f"  Raw OCR ({len(raw_text)} chars): {raw_text[:80]}...")

            fields = extract_fields(raw_text)
            fields.raw_text = raw_text
            fields.confidence = round(_clamp(0.55 * fields.confidence + 0.45 * ocr_confidence), 4)
            profile, profile_score = _classify_image_adversarial_profile(fields, raw_text, fields.confidence, trace)
            fields.image_profile = profile
            fields.image_profile_score = profile_score
            fields.failure_map["image_profile"] = profile
            all_raw_text.append(raw_text)

            per_image_results.append(fields)
            logger.info(
                f"  Ã¢â€ â€™ name={fields.medicine_name!r} "
                f"batch={fields.batch_number!r} "
                f"exp={fields.expiry_date!r} "
                f"qr={'yes' if fields.qr_data else 'no'} "
                f"conf={fields.confidence}"
            )

        except Exception as exc:
            logger.error(f"Image {idx + 1} failed: {exc}")
            per_image_results.append(MedicineFields())  # empty placeholder
            all_raw_text.append("")

    # Stage 6: Fusion
    final_fields, conflicts, derived = fuse_results(per_image_results)
    combined_raw_text = "\n\n--- IMAGE BREAK ---\n\n".join(all_raw_text)
    final_fields = _reconstruct_structured_fields(final_fields, combined_raw_text)
    image_pools = _collect_image_pools(per_image_results)
    image_weights = [
        max(float(image.confidence), 0.01)
        * (_profile_weight(image.image_profile) if DEMO_STABILITY_MODE else 1.0)
        for image in per_image_results
    ]
    soft_decisions = {
        "medicine_name": _soft_field_decision("medicine_name", image_pools, image_weights),
        "manufacturer": _soft_field_decision("manufacturer", image_pools, image_weights),
    }
    for field_name, decision in soft_decisions.items():
        if decision["state"] != "REJECTED":
            setattr(final_fields, field_name, str(decision["value"]))
        else:
            setattr(final_fields, field_name, "")
        if field_name == "medicine_name":
            final_fields.medicine_name_confidence = float(decision["confidence_score"])
        elif field_name == "manufacturer":
            final_fields.manufacturer_confidence = float(decision["confidence_score"])

    conflicts = [
        conflict
        for conflict in conflicts
        if not (
            conflict.startswith("medicine_name mismatch")
            and soft_decisions["medicine_name"]["state"] != "REJECTED"
        )
        and not (
            conflict.startswith("manufacturer mismatch")
            and soft_decisions["manufacturer"]["state"] != "REJECTED"
        )
    ]

    agreement_scores = []
    for field_name in CORE_FIELD_NAMES:
        final_val = getattr(final_fields, field_name).strip()
        if not final_val:
            continue
        agree = sum(
            1 for img in per_image_results
            if _normalize_for_field(field_name, getattr(img, field_name)) == final_val
        )
        agreement_scores.append(agree / len(per_image_results))
    agreement_score = statistics.mean(agreement_scores) if agreement_scores else 0.0

    consistency_fields = ["batch_number", "expiry_date", "manufacturer"]
    consistent = sum(1 for f in consistency_fields if f not in {c.split(":", 1)[0] for c in conflicts})
    consistency_score = consistent / len(consistency_fields)

    missing = sum(1 for f in CORE_FIELD_NAMES if not getattr(final_fields, f).strip())
    missing_field_ratio = missing / len(CORE_FIELD_NAMES)
    mean_conf = statistics.mean(image_weights) if image_weights else 0.0
    ocr_confidence = round(0.6 * mean_conf + 0.4 * agreement_score, 4)
    derived = DerivedParameters(
        agreement_score=round(agreement_score, 4),
        consistency_score=round(consistency_score, 4),
        conflict_count=len(conflicts),
        missing_field_ratio=round(missing_field_ratio, 4),
        ocr_confidence=ocr_confidence,
    )
    validation = validate_fields(final_fields, raw_text=combined_raw_text)
    evidence = _build_field_evidence(combined_raw_text, per_image_results, final_fields, derived)
    for field_name, decision in soft_decisions.items():
        evidence[field_name]["field_state"] = decision["state"]
        evidence[field_name]["empty_reason"] = "" if decision["state"] != "REJECTED" else decision["reason"]
        evidence[field_name]["rejection_reason"] = "" if decision["state"] != "REJECTED" else decision["reason"]
        evidence[field_name]["final_score"] = round(float(decision["confidence_score"]), 4)
        evidence[field_name]["confidence_score"] = round(float(decision["confidence_score"]), 4)
        evidence[field_name]["decision_value"] = decision["value"]
        evidence[field_name]["decision_state"] = decision["state"]
        evidence[field_name]["evidence_sources"] = decision.get("evidence_sources", [])
    field_decisions = _build_field_decisions(final_fields, per_image_results, evidence)
    final_fields, field_decisions, validation_flags = evidence_truth_validator(
        final_fields,
        per_image_results,
        evidence,
        field_decisions,
        combined_raw_text,
    )
    truth_validation = validation_flags
    evidence = _build_field_evidence(combined_raw_text, per_image_results, final_fields, derived)
    field_decisions = _build_field_decisions(final_fields, per_image_results, evidence)
    for field_name in CORE_FIELD_NAMES:
        field_decisions[field_name]["validation_flags"] = validation_flags.get(
            field_name,
            {
                "evidence_sufficient": False,
                "no_contradiction": False,
                "cross_image_supported": False,
                "noise_within_limit": False,
            },
        )
    fallback_used = any(bool(trace.get("fallback_triggered")) for trace in ocr_traces)
    ocr_calls_count = sum(int(trace.get("ocr_calls", 0) or 0) for trace in ocr_traces)
    stage_1_used = all(bool(trace.get("stage_1_used")) for trace in ocr_traces) if ocr_traces else False
    stage_2_used = all(bool(trace.get("stage_2_used")) for trace in ocr_traces) if ocr_traces else False
    tokens_extracted = sum(int(trace.get("tokens_extracted", 0) or 0) for trace in ocr_traces)
    unique_tokens = sum(int(trace.get("unique_tokens", 0) or 0) for trace in ocr_traces)

    # Build output dict
    result: dict = {
        "final_data": _fields_to_dict(final_fields, include_confidence=False),
        "per_image_data": [_fields_to_dict(f) for f in per_image_results],
        "derived_parameters": asdict(derived),
        "validation": asdict(validation),
        "conflicts": conflicts,
        "raw_text_combined": combined_raw_text,
        "raw_text": combined_raw_text,
        "confidence": derived.ocr_confidence,
        "fallback_used": fallback_used,
        "OCR_calls_count": ocr_calls_count,
        "stage_1_used": stage_1_used,
        "stage_2_used": stage_2_used,
        "tokens_extracted": tokens_extracted,
        "unique_tokens": unique_tokens,
        "ocr_traces": ocr_traces,
        "evidence": evidence,
        "field_decisions": field_decisions,
        "truth_validation": validation_flags,
    }

    logger.info(
        f"Pipeline complete. OCR confidence={derived.ocr_confidence} "
        f"conflicts={derived.conflict_count}"
    )
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fields_to_dict(fields: MedicineFields, include_confidence: bool = True) -> dict:
    d = {
        "medicine_name": fields.medicine_name,
        "batch_number":  fields.batch_number,
        "expiry_date":   fields.expiry_date,
        "mfg_date":      fields.mfg_date,
        "manufacturer":  fields.manufacturer,
        "qr_data":       fields.qr_data,
        "failure_map":   fields.failure_map,
        "image_profile": fields.image_profile,
        "image_profile_score": round(float(fields.image_profile_score or 0.0), 4),
        "semantic_variance_score": round(float(fields.semantic_variance_score or 0.0), 4),
    }
    if include_confidence:
        d["confidence"] = fields.confidence
        d["medicine_name_confidence"] = fields.medicine_name_confidence
        d["batch_confidence"] = fields.batch_confidence
        d["expiry_confidence"] = fields.expiry_confidence
        d["mfg_confidence"] = fields.mfg_confidence
        d["manufacturer_confidence"] = fields.manufacturer_confidence
        d["raw_text"] = fields.raw_text
    return d


def _empty_result() -> dict:
    empty_final = MedicineFields()
    empty_evidence = _build_field_evidence("", [], empty_final, DerivedParameters())
    empty_field_decisions = _build_field_decisions(empty_final, [], empty_evidence)
    empty_truth_validation = {
        field_name: {
            "evidence_sufficient": False,
            "no_contradiction": True,
            "cross_image_supported": False,
            "noise_within_limit": True,
        }
        for field_name in CORE_FIELD_NAMES
    }
    return {
        "final_data": _fields_to_dict(empty_final, include_confidence=False),
        "per_image_data": [],
        "derived_parameters": asdict(DerivedParameters()),
        "validation": asdict(ValidationResult()),
        "conflicts": [],
        "raw_text_combined": "",
        "raw_text": "",
        "confidence": 0.0,
        "fallback_used": False,
        "OCR_calls_count": 0,
        "stage_1_used": False,
        "stage_2_used": False,
        "tokens_extracted": 0,
        "unique_tokens": 0,
        "ocr_traces": [],
        "evidence": empty_evidence,
        "field_decisions": empty_field_decisions,
        "truth_validation": empty_truth_validation,
    }


# ---------------------------------------------------------------------------
# Demo / Smoke Test (no real images required)
# ---------------------------------------------------------------------------

def _demo_with_synthetic_data():
    """
    Runs the pipeline on three synthetic MedicineFields objects to demonstrate
    the fusion + conflict detection logic without needing real image files.
    """
    print("\n" + "=" * 60)
    print("  MediShield OCR Ã¢â‚¬â€ Synthetic Demo")
    print("=" * 60)

    # Simulate three images with slightly different OCR outputs
    sample_results = [
        MedicineFields(
            medicine_name="Amoxicillin",
            batch_number="BT2024A",
            expiry_date="06/2026",
            mfg_date="06/2024",
            manufacturer="Cipla Ltd",
            confidence=0.91,
            raw_text="Amoxicillin 500mg\nBatch No: BT2024A\nMfg: 06/2024 Exp: 06/2026\nCipla Ltd",
        ),
        MedicineFields(
            medicine_name="Amoxicillin",
            batch_number="BT2024A",
            expiry_date="06/2026",
            mfg_date="",             # missed by this image
            manufacturer="Cipla Ltd",
            confidence=0.78,
            raw_text="AMOXICILLIN 500MG\nBT2024A\nExp 06/2026\nCipla Ltd",
        ),
        MedicineFields(
            medicine_name="Amoxicillin",
            batch_number="BT2024B",  # Ã¢â€ Â conflict introduced here
            expiry_date="06/2026",
            mfg_date="06/2024",
            manufacturer="Cipla Ltd",
            confidence=0.65,
            raw_text="Amoxicillin\nBatch: BT2024B\nMfg 06/2024 Exp 06/2026\nCipla Ltd",
        ),
    ]

    final_fields, conflicts, derived = fuse_results(sample_results)

    output = {
        "final_data": _fields_to_dict(final_fields, include_confidence=False),
        "per_image_data": [_fields_to_dict(f) for f in sample_results],
        "derived_parameters": asdict(derived),
        "conflicts": conflicts,
        "raw_text_combined": "\n".join(f.raw_text for f in sample_results),
    }

    print(json.dumps(output, indent=2))
    return output


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _demo_with_synthetic_data()



# ============================================================================
# OCR CONTRACT GATEWAY - ORCHESTRATOR INTERFACE
# ============================================================================
# This function bridges the deterministic ocr_core() contract with the
# pipeline orchestrator's expected OCREngineOutput format.
#
# CRITICAL: Uses ONLY ocr_core() for Tesseract calls (2 per image).
# NO OCREngine calls. NO additional pytesseract invocations.
#
# ============================================================================

def process_medicine_images_with_ocr_core(image_paths):
    """
    Process medicine images using deterministic ocr_core() gateway.
    
    CONTRACT:
    - Exactly 2 pytesseract calls per image (enforced by ocr_core)
    - Returns OCREngineOutput compatible with pipeline orchestrator
    - No hidden OCR routing or fallback paths
    """
    from pipeline_schemas import OCREngineOutput, OCRImageResult, OCRFieldDetection
    
    image_results = []
    combined_raw_text = []
    start_time = time.time()
    
    for image_path in image_paths:
        try:
            # Use ocr_core() as single deterministic OCR gate (2 calls per image)
            raw_text, avg_confidence = ocr_core(image_path)
            combined_raw_text.append(raw_text)
            
            # Extract fields from raw text using legacy helpers
            medicine_name = _extract_strict_medicine_name(raw_text) or ""
            batch_number = _extract_strict_batch(raw_text) or ""
            expiry_date = _extract_strict_expiry(raw_text) or ""
            mfg_date = _extract_strict_mfg(raw_text) or ""
            manufacturer = _extract_strict_manufacturer(raw_text) or ""
            
            # Create per-field detection objects
            result = OCRImageResult(
                image_path=image_path,
                medicine_name=OCRFieldDetection(
                    value=medicine_name if medicine_name else None,
                    confidence=avg_confidence if medicine_name else 0.0,
                    raw_value=medicine_name or None,
                ),
                batch_number=OCRFieldDetection(
                    value=batch_number if batch_number else None,
                    confidence=avg_confidence if batch_number else 0.0,
                    raw_value=batch_number or None,
                ),
                expiry_date=OCRFieldDetection(
                    value=expiry_date if expiry_date else None,
                    confidence=avg_confidence if expiry_date else 0.0,
                    raw_value=expiry_date or None,
                ),
                mfg_date=OCRFieldDetection(
                    value=mfg_date if mfg_date else None,
                    confidence=avg_confidence if mfg_date else 0.0,
                    raw_value=mfg_date or None,
                ),
                manufacturer=OCRFieldDetection(
                    value=manufacturer if manufacturer else None,
                    confidence=avg_confidence if manufacturer else 0.0,
                    raw_value=manufacturer or None,
                ),
                raw_text=raw_text,
                overall_confidence=avg_confidence,
            )
            image_results.append(result)
            
        except Exception as exc:
            logger.warning(f"Error processing {image_path}: {exc}")
            image_results.append(
                OCRImageResult(
                    image_path=image_path,
                    medicine_name=OCRFieldDetection(value=None, confidence=0.0, raw_value=None),
                    batch_number=OCRFieldDetection(value=None, confidence=0.0, raw_value=None),
                    expiry_date=OCRFieldDetection(value=None, confidence=0.0, raw_value=None),
                    mfg_date=OCRFieldDetection(value=None, confidence=0.0, raw_value=None),
                    manufacturer=OCRFieldDetection(value=None, confidence=0.0, raw_value=None),
                    raw_text="",
                    overall_confidence=0.0,
                )
            )
    
    processing_time = time.time() - start_time
    
    return OCREngineOutput(
        image_results=image_results,
        raw_combined_text="\n".join(combined_raw_text),
        processing_time_seconds=processing_time,
        notes=["OCR_CORE_CONTRACT: 2_tesseract_calls_per_image"],
    )
