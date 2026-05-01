import re
from typing import Any

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

try:
    import pytesseract
except Exception:  # pragma: no cover
    pytesseract = None

try:
    from .predictor import find_medicine
except Exception:  # pragma: no cover
    def find_medicine(query: str) -> dict:
        return {"medicine": None, "score": 0.0, "suggestions": []}

DATE_PATTERN = r"(\d{1,2}[\-/]\d{1,2}[\-/]\d{2,4}|\d{4}[\-/]\d{1,2}[\-/]\d{1,2}|\d{1,2}[\-/]\d{4})"
OCR_CONFIGS = (
    "--oem 3 --psm 6",
    "--oem 3 --psm 11",
    "--oem 3 --psm 12",
    "--oem 3 --psm 7",
)


def _normalize_candidate(value: str) -> str:
    return " ".join(value.strip().split())


def _looks_like_product_name(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    if re.fullmatch(r"[A-Z0-9][A-Z0-9\-+/]{2,}", text):
        return True
    if re.search(r"\d", text) and re.search(r"[A-Za-z]", text):
        return True
    if "-" in text and re.search(r"[A-Za-z]", text):
        return True
    return False


def _prepare_variants(image: Any) -> list[Any]:
    variants = [image]
    if cv2 is None or not hasattr(image, "shape"):
        return variants

    try:
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        denoised = cv2.fastNlMeansDenoising(blurred, None, 12, 7, 21)
        resized = cv2.resize(gray, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
        _, thresh = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        adaptive = cv2.adaptiveThreshold(
            denoised,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            11,
        )
        variants.extend([gray, denoised, resized, thresh, adaptive])
    except Exception:
        pass

    unique_variants: list[Any] = []
    seen_ids: set[int] = set()
    for variant in variants:
        variant_id = id(variant)
        if variant_id in seen_ids:
            continue
        seen_ids.add(variant_id)
        unique_variants.append(variant)
    return unique_variants


def _ocr_variant(image: Any, config: str) -> tuple[str, float]:
    if pytesseract is None:
        return "", 0.0

    try:
        text = pytesseract.image_to_string(image, config=config)
    except Exception:
        text = ""

    try:
        data = pytesseract.image_to_data(image, config=config, output_type=pytesseract.Output.DICT)
        conf_values = [float(value) for value in data.get("conf", []) if str(value).strip() not in {"", "-1"}]
        confidence = sum(conf_values) / len(conf_values) if conf_values else 0.0
    except Exception:
        confidence = float(len(text)) / 8.0 if text else 0.0

    return text, min(100.0, max(0.0, float(confidence)))


def _medicine_hint(text: str) -> tuple[str | None, float]:
    lines = [_normalize_candidate(line) for line in text.splitlines()]
    best_line = None
    best_score = 0.0

    for line in lines:
        if not line:
            continue
        lowered = line.lower()
        if any(token in lowered for token in ("batch", "lot", "exp", "expiry", "mfg", "manufacturer", "mrp", "price")):
            continue
        prediction = find_medicine(line)
        score = float(prediction.get("score", 0.0) or 0.0)
        if _looks_like_product_name(line):
            score = max(score, 0.95)
            medicine = prediction.get("medicine") or {}
            best_candidate = line
            if best_candidate and score > best_score:
                best_line = best_candidate
                best_score = score
            continue
        if score > best_score:
            medicine = prediction.get("medicine") or {}
            best_line = medicine.get("name") if isinstance(medicine, dict) and medicine.get("name") else line
            best_score = score

    if best_line:
        return best_line, best_score

    compact = _normalize_candidate(text)
    if compact:
        prediction = find_medicine(compact)
        score = float(prediction.get("score", 0.0) or 0.0)
        if score >= best_score and score >= 0.5:
            medicine = prediction.get("medicine") or {}
            return (medicine.get("name") if isinstance(medicine, dict) and medicine.get("name") else compact), score

    ranked_lines: list[tuple[float, str]] = []
    for line in lines:
        if not line:
            continue
        lowered = line.lower()
        if any(token in lowered for token in ("batch", "lot", "exp", "expiry", "mfg", "manufacturer", "mrp", "price")):
            continue
        prediction = find_medicine(line)
        score = float(prediction.get("score", 0.0) or 0.0)
        if score >= 0.25:
            medicine = prediction.get("medicine") or {}
            candidate = medicine.get("name") if isinstance(medicine, dict) and medicine.get("name") else line
            ranked_lines.append((score, candidate))

    if ranked_lines:
        ranked_lines.sort(key=lambda item: (-item[0], len(item[1]), item[1].lower()))
        return ranked_lines[0][1], ranked_lines[0][0]

    return None, 0.0


def _medicine_fallback_candidate(lines: list[str]) -> str:
    best_line = ""
    best_score = float("-inf")
    dosage_tokens = ("mg", "mcg", "ml", "tab", "tablet", "cap", "capsule", "syrup", "drop", "ointment")

    for line in lines:
        if not line:
            continue
        lowered = line.lower()
        if any(token in lowered for token in ("batch", "lot", "exp", "expiry", "mfg", "manufacturer", "mrp", "price")):
            continue

        prediction = find_medicine(line)
        score = float(prediction.get("score", 0.0) or 0.0)
        tokens = re.findall(r"[A-Za-z0-9]+", line)

        if _looks_like_product_name(line):
            score += 0.35
        if any(token in lowered for token in dosage_tokens):
            score += 0.22
        if re.search(r"\d", line):
            score += 0.15
        if 2 <= len(tokens) <= 5:
            score += 0.08
        if len(tokens) == 1:
            score += 0.05
        if line.isupper():
            score += 0.08

        candidate = prediction.get("medicine") or {}
        if _looks_like_product_name(line):
            candidate_name = line
        else:
            candidate_name = candidate.get("name") if isinstance(candidate, dict) and candidate.get("name") else line
        if score > best_score:
            best_score = score
            best_line = candidate_name

    return best_line


def extract_text(image: Any) -> tuple[str, float]:
    if pytesseract is None:
        return "", 0.0

    best_text = ""
    best_score = -1.0
    best_confidence = 0.0

    for variant in _prepare_variants(image):
        for config in OCR_CONFIGS:
            text, confidence = _ocr_variant(variant, config)
            normalized_text = _normalize_candidate(text)
            if not normalized_text:
                continue
            medicine_hint, medicine_score = _medicine_hint(normalized_text)
            composite_score = medicine_score * 100.0 + confidence * 0.4 + min(len(normalized_text), 400) * 0.05
            if medicine_hint:
                composite_score += 20.0
            if composite_score > best_score:
                best_score = composite_score
                best_text = normalized_text
                best_confidence = confidence if confidence > 0.0 else min(100.0, float(len(normalized_text)) / 8.0)

    if best_text:
        return best_text, min(100.0, best_confidence)

    try:
        text = pytesseract.image_to_string(image)
    except Exception:
        return "", 0.0
    confidence = min(100.0, float(len(text)) / 8.0)
    return text, confidence


def _find(pattern: str, text: str, flags: int = re.IGNORECASE) -> str | None:
    match = re.search(pattern, text, flags)
    return match.group(1).strip() if match else None


def parse_fields(text: str) -> dict:
    medicine_hint, medicine_hint_score = _medicine_hint(text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    medicine_fallback = _medicine_fallback_candidate(lines)
    fields = {
        "medicine_name": _find(r"(?:medicine|name)\s*[:\-]\s*([^\n]+)", text),
        "batch_number": _find(r"(?:batch|lot)\s*(?:no|number)?\s*[:\-]?\s*([A-Z0-9\-_/]{4,})", text),
        "mfg_date": _find(r"(?:mfg|manu(?:facture)?d?)\s*(?:date)?\s*[:\-]?\s*(%s)" % DATE_PATTERN, text),
        "exp_date": _find(r"(?:exp|expiry|expires?)\s*(?:date)?\s*[:\-]?\s*(%s)" % DATE_PATTERN, text),
        "manufacturer": _find(r"(?:manufacturer|mfg\s*by|made\s*by)\s*[:\-]\s*([^\n]+)", text),
    }

    if medicine_hint and medicine_hint_score >= 0.5:
        fields["medicine_name"] = medicine_hint
    if not fields["medicine_name"]:
        if medicine_fallback:
            fields["medicine_name"] = medicine_fallback

    return fields
