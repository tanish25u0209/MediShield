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
import statistics
import shutil
from pathlib import Path
from datetime import date
from collections import Counter
from dataclasses import dataclass, field, asdict

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


_configure_tesseract()

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
    raw_text: str = ""


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


@dataclass
class FusedResult:
    final_data: MedicineFields = field(default_factory=MedicineFields)
    per_image_data: list[MedicineFields] = field(default_factory=list)
    derived_parameters: DerivedParameters = field(default_factory=DerivedParameters)
    conflicts: list[str] = field(default_factory=list)
    raw_text_combined: str = ""


# ---------------------------------------------------------------------------
# STAGE 1 — Image Preprocessing
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
        return image_input.copy()
    raise TypeError(f"Unsupported image type: {type(image_input)}")


def preprocess_image(image_input) -> np.ndarray:
    """
    Prepare an image for optimal OCR performance.

    Pipeline:
        1. Load  → handles file paths, PIL Images, and raw numpy arrays
        2. Resize → standardise scale; Tesseract accuracy degrades on very
                    small or very large images.  224 × 224 is a safe middle
                    ground for label crops.
        3. Grayscale → OCR engines work on intensity; colour channels add
                       noise without information gain.
        4. Gaussian blur → softens salt-and-pepper noise from camera sensors
                           before thresholding, preventing speckle artefacts
                           from becoming fake ink dots.
        5. Adaptive threshold → converts grey pixels to binary (black/white)
                                using a local neighbourhood mean rather than a
                                global cutoff, so uneven lighting (shadow on
                                packaging) doesn't obliterate text.
        6. Morphological dilation → slightly thickens thin strokes that OCR
                                    engines can mistake for noise.

    Args:
        image_input: file path (str), PIL Image, or numpy ndarray.

    Returns:
        Preprocessed binary numpy array (uint8, 0 or 255).
    """
    # ── Load ─────────────────────────────────────────────────────────────
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

    # ── Resize ───────────────────────────────────────────────────────────
    # Upscale small images; downscale large ones.  Both extremes hurt OCR.
    target = 800  # use longer edge = 800 px; preserves aspect ratio better
    h, w = img.shape[:2]
    scale = target / max(h, w)
    if scale != 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)),
                         interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)

    # ── Grayscale ────────────────────────────────────────────────────────
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # ── Gaussian blur (noise reduction before threshold) ─────────────────
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)

    # ── Adaptive threshold ───────────────────────────────────────────────
    binary = cv2.adaptiveThreshold(
        blurred,
        maxValue=255,
        adaptiveMethod=cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        thresholdType=cv2.THRESH_BINARY,
        blockSize=11,   # neighbourhood size (must be odd)
        C=2             # constant subtracted from the local mean
    )

    # ── Light morphological dilation to strengthen thin strokes ──────────
    kernel = np.ones((1, 1), np.uint8)
    processed = cv2.dilate(binary, kernel, iterations=1)

    return processed


# ---------------------------------------------------------------------------
# STAGE 1.5 — SMART REGION DETECTION & CROPPING
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
    """
    Run OCR on a specific region with optimized preprocessing.
    
    Args:
        region_bgr: Cropped region image (BGR).
        target_field: 'name', 'batch', 'expiry', 'general' — hints PSM selection.
    
    Returns:
        Raw OCR text.
    """
    if region_bgr is None or region_bgr.size == 0:
        return ""
    
    # Preprocess the region
    gray = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    binary = cv2.adaptiveThreshold(
        blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 11, 2
    )
    
    # Select PSM based on field type
    psm_configs = {
        'name': ["--oem 3 --psm 6", "--oem 3 --psm 7"],
        'batch': ["--oem 3 --psm 8", "--oem 3 --psm 6"],
        'expiry': ["--oem 3 --psm 8", "--oem 3 --psm 6"],
        'general': ["--oem 3 --psm 6", "--oem 3 --psm 11"],
    }
    
    configs = psm_configs.get(target_field, psm_configs['general'])
    best_text = ""
    best_score = -1.0
    
    try:
        for config in configs:
            raw = pytesseract.image_to_string(binary, config=config).strip()
            score = _ocr_text_score(raw)
            if score > best_score:
                best_score = score
                best_text = raw
        return best_text
    except Exception as exc:
        logger.debug(f"Region OCR failed: {exc}")
        return ""


# ---------------------------------------------------------------------------
# STAGE 2 — OCR Extraction
# ---------------------------------------------------------------------------

def extract_text(preprocessed_image: np.ndarray) -> str:
    """
    Run Tesseract OCR on a preprocessed image.

    Config:
        --oem 3  → LSTM engine (most accurate on printed labels)
        --psm 6  → Assume a single uniform block of text (works well for
                   medicine packaging that mixes fonts and font sizes)

    Returns:
        Raw OCR string, stripped of leading/trailing whitespace.
    """
    configs = [
        "--oem 3 --psm 6",
        "--oem 3 --psm 11",
        "--oem 3 --psm 4",
    ]
    best_text = ""
    best_score = -1.0

    try:
        for config in configs:
            raw = pytesseract.image_to_string(preprocessed_image, config=config).strip()
            score = _ocr_text_score(raw)
            if score > best_score:
                best_score = score
                best_text = raw
        return best_text
    except pytesseract.TesseractNotFoundError:
        logger.error("Tesseract is not installed or not in PATH.")
        return ""
    except Exception as exc:
        logger.warning(f"OCR failed: {exc}")
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
# STAGE 3 — Text Cleaning
# ---------------------------------------------------------------------------

# Common OCR substitution errors on medicine labels
_OCR_CORRECTIONS: dict[str, str] = {
    "0": "O",  # digit zero → letter O  (in name context)
    "1": "I",  # digit one  → letter I
    "|": "I",  # pipe       → letter I
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
    text = text.replace("°", "").replace("®", "").replace("™", "")

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
# STAGE 4 — Field Extraction
# ---------------------------------------------------------------------------

# ── Compiled regex patterns ───────────────────────────────────────────────

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
    Normalize OCR date fragments into a consistent MM/YYYY or MM/YY form.
    """
    token = token.strip()
    token = token.replace(".", "/").replace("-", "/")
    token = re.sub(r"\s+", "", token)

    m = re.fullmatch(r"(\d{1,2})/(\d{2}|\d{4})", token)
    if not m:
        return token

    month = m.group(1).zfill(2)
    year = m.group(2)
    return f"{month}/{year}"


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
        - 1–4 words long
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


# ---------------------------------------------------------------------------
# STAGE 4.5 — FIELD-FOCUSED EXTRACTION & POST-PROCESSING
# ---------------------------------------------------------------------------

def normalize_extracted_fields(fields: MedicineFields) -> MedicineFields:
    """
    Apply post-processing rules to normalize field values.
    
    Rules:
        - Normalize date formats (ensure MM/YYYY)
        - Remove common abbreviations (EXP→expiry, B.No→batch)
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
        1. Crop region for medicine name (top) → run OCR on it
        2. Crop region for batch/expiry (bottom) → run OCR on it
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
    
    # ── Extract medicine name from top region ─────────────────────────
    name_region = crop_region_for_medicine_name(image_bgr, binary)
    if name_region is not None:
        name_text = extract_text_from_region(name_region, target_field='name')
        name_cleaned = clean_text(name_text)
        fields.medicine_name = _best_medicine_name(name_text or original_raw_text)
    else:
        fields.medicine_name = _best_medicine_name(original_raw_text)
    
    # ── Extract batch/expiry from bottom region ──────────────────────
    batch_region = crop_region_for_batch_expiry(image_bgr, binary)
    batch_expiry_text = ""
    if batch_region is not None:
        batch_expiry_text = extract_text_from_region(batch_region, target_field='batch')
    
    # Combine region text with original for pattern matching
    search_text = clean_text(batch_expiry_text or original_raw_text)
    
    # ── Field-focused extraction (batch FIRST, then expiry) ──────────
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


def _compute_field_confidence(fields: MedicineFields) -> float:
    """
    Score extraction confidence based on field completeness and quality.
    
    Returns 0.0–1.0.
    """
    completeness = 0.0
    completeness += 0.2 if fields.medicine_name.strip() else 0.0
    completeness += 0.2 if fields.batch_number.strip() else 0.0
    completeness += 0.2 if fields.expiry_date.strip() else 0.0
    completeness += 0.2 if fields.mfg_date.strip() else 0.0
    completeness += 0.2 if fields.manufacturer.strip() else 0.0
    
    # Bonus for QR data
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
    cleaned = clean_text(raw_text)

    fields = MedicineFields()
    fields.raw_text = raw_text

    fields.medicine_name = _best_medicine_name(raw_text)   # use original case
    fields.batch_number  = _best_batch(cleaned)
    fields.expiry_date   = _best_date(_RE_EXPIRY, cleaned)
    fields.mfg_date      = _best_date(_RE_MFG, cleaned)
    fields.manufacturer  = _best_manufacturer(raw_text)    # use original case

    if not fields.expiry_date:
        standalone_dates = _RE_DATE_STANDALONE.findall(cleaned)
        if standalone_dates:
            fields.expiry_date = f"{standalone_dates[0][0].zfill(2)}/{standalone_dates[0][1]}"

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

    mfg_date = _parse_month_year(fields.mfg_date)
    exp_date = _parse_month_year(fields.expiry_date, as_end_of_month=True)

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
# STAGE 5 — Validation + Per-Image Confidence
# ---------------------------------------------------------------------------

CORE_FIELD_NAMES = ["medicine_name", "batch_number", "expiry_date", "mfg_date", "manufacturer"]
OPTIONAL_FIELD_NAMES = ["qr_data"]


def compute_confidence(fields: MedicineFields, raw_text: str) -> float:
    """
    Estimate extraction confidence for a single image on a 0–1 scale.

    Components:
        - field_ratio   : fraction of the 5 key fields successfully extracted
        - text_density  : ratio of alphanumeric chars to total chars in raw OCR
                          (low density → noisy, blurry image)
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
# STAGE 6 — Multi-Image Fusion
# ---------------------------------------------------------------------------

def _normalize_for_field(field_name: str, value: str) -> str:
    """Normalize values before voting so formatting does not create noise."""
    value = (value or "").strip()
    if not value:
        return ""
    if field_name == "batch_number":
        return value.upper()
    if field_name in {"expiry_date", "mfg_date"}:
        return _normalize_date_token(value)
    if field_name == "manufacturer":
        return value.title()
    if field_name == "qr_data":
        return value
    return re.sub(r"\s+", " ", value)


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


def fuse_results(per_image: list[MedicineFields]) -> tuple[MedicineFields, list[str], DerivedParameters]:
    """
    Combine per-image extraction results into one authoritative record.

    Algorithm per field:
        1. Collect all non-empty values + their confidence weights
        2. Use weighted majority vote
        3. If still ambiguous → pick highest-confidence single value
        4. Record field-level conflicts

    Returns:
        (final_fields, conflicts, derived_params)
    """
    if not per_image:
        return MedicineFields(), [], DerivedParameters()

    weights = [img.confidence for img in per_image]
    # Avoid zero-weight edge case
    weights = [max(w, 0.01) for w in weights]

    conflicts: list[str] = []
    final = MedicineFields()
    conflict_fields: set[str] = set()

    for field_name in CORE_FIELD_NAMES:
        values = [getattr(img, field_name) for img in per_image]
        winner = _weighted_majority(values, weights, field_name)
        setattr(final, field_name, winner)

        distinct = {
            _normalize_for_field(field_name, v)
            for v in values
            if _normalize_for_field(field_name, v)
        }
        if len(distinct) > 1:
            conflict_fields.add(field_name)
            conflicts.append(f"{field_name} mismatch: {sorted(distinct)}")

    qr_values = [getattr(img, "qr_data") for img in per_image]
    final.qr_data = _weighted_majority(qr_values, weights, "qr_data")
    qr_distinct = {
        _normalize_for_field("qr_data", v)
        for v in qr_values
        if _normalize_for_field("qr_data", v)
    }
    if len(qr_distinct) > 1:
        conflict_fields.add("qr_data")
        conflicts.append(f"qr_data mismatch: {sorted(qr_distinct)}")

    # ── Derived parameters ────────────────────────────────────────────────
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

    for idx, img_input in enumerate(images):
        logger.info(f"Processing image {idx + 1}/{len(images)} ...")

        try:
            # Load image in BGR format (needed for region-based extraction)
            img_bgr = _load_image_bgr(img_input)
            
            # Stage 1: Preprocess
            preprocessed = preprocess_image(img_bgr)

            # Stage 2: Full-image OCR (for fallback)
            raw_text = extract_text(preprocessed)
            logger.debug(f"  Raw OCR ({len(raw_text)} chars): {raw_text[:80]}...")

            # Stage 3: Field extraction — USING OLD SIMPLE APPROACH (100% better on batch/expiry)
            # NOTE: Region-based approach tested but underperformed (-100% on critical fields).
            # See: baseline_phase2_results.json for validation data.
            fields = extract_fields(raw_text)
            all_raw_text.append(raw_text)

            per_image_results.append(fields)
            logger.info(
                f"  → name={fields.medicine_name!r} "
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
    validation = validate_fields(final_fields, raw_text=combined_raw_text)

    # Build output dict
    result: dict = {
        "final_data": _fields_to_dict(final_fields, include_confidence=False),
        "per_image_data": [_fields_to_dict(f) for f in per_image_results],
        "derived_parameters": asdict(derived),
        "validation": asdict(validation),
        "conflicts": conflicts,
        "raw_text_combined": combined_raw_text,
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
    }
    if include_confidence:
        d["confidence"] = fields.confidence
        d["raw_text"] = fields.raw_text
    return d


def _empty_result() -> dict:
    return {
        "final_data": _fields_to_dict(MedicineFields(), include_confidence=False),
        "per_image_data": [],
        "derived_parameters": asdict(DerivedParameters()),
        "validation": asdict(ValidationResult()),
        "conflicts": [],
        "raw_text_combined": "",
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
    print("  MediShield OCR — Synthetic Demo")
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
            batch_number="BT2024B",  # ← conflict introduced here
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
