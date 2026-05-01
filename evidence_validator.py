"""
Evidence Validator - truth verification layer for field decisions.

Runs after fusion and before final output. Implements strict rules:
- Evidence sufficiency (>=2 independent signals or 1+structural uniqueness)
- Consistency (no conflicting evidence)
- Evidence-decision alignment (all supporting evidence must imply final value)
- Noise dominance check (reject if noisy tokens dominate)

Exposes `validate_evidence(fusion_output, ocr_output)` which returns:
 - final_fields: dict[field_name -> FinalField]
 - summary: dict with keys {any_rejected, suggestions_for_refusion}

This module does NOT modify OCR or fusion data; it only inspects and suggests
which tokens to remove if a re-evaluation (secondary fusion pass) is desired.
"""

import re
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Dict, Any, List, Tuple

from pipeline_schemas import FinalField


CORE_FIELDS = ["medicine_name", "batch_number", "expiry_date", "mfg_date", "manufacturer"]

STRICT_FIELDS = {"batch_number", "expiry_date", "mfg_date"}
DATE_FIELDS = {"expiry_date", "mfg_date"}
ALLOWED_REJECTION_REASONS = {
    "NO_VALID_CANDIDATES",
    "CROSS_CONFLICT_BLOCKED",
    "FORMAT_INVALID",
    "WEAK_SIGNAL_REJECTED",
    "LOW_OCR_CONFIDENCE",
}

FAILURE_MODE_MAP = {
    "NO_VALID_CANDIDATES": "INSUFFICIENT_EVIDENCE",
    "CROSS_CONFLICT_BLOCKED": "CONSISTENT_CONFLICT",
    "FORMAT_INVALID": "FORMAT_VIOLATION",
    "WEAK_SIGNAL_REJECTED": "INSUFFICIENT_EVIDENCE",
    "LOW_OCR_CONFIDENCE": "NOISE_FAILURE",
}

IMAGE_PROFILE_WEIGHTS = {
    "CLEAN_SIGNAL": 1.00,
    "OCR_NOISY": 0.82,
    "PARTIAL_LABEL": 0.68,
    "HEAVY_DISTORTION": 0.50,
}

DEMO_STABILITY_MODE = True

CONFIRMATION_THRESHOLD = 0.62
REJECTION_CONFLICT_THRESHOLD = 0.34

DATE_ANCHORS = {
    "expiry_date": ("exp", "expiry", "use before", "use-before", "useby", "use by"),
    "mfg_date": ("mfg", "mfd", "manufactured", "manufacture", "manufacturing"),
}


def _get_image_results(ocr_output: Any) -> List[Any]:
    if ocr_output is None:
        return []
    if isinstance(ocr_output, dict):
        return list(ocr_output.get("image_results", []) or [])
    return list(getattr(ocr_output, "image_results", []) or [])


def _field_detection(image_result: Any, field: str) -> Any:
    if isinstance(image_result, dict):
        return image_result.get(field)
    return getattr(image_result, field, None)


def _field_raw_text(image_result: Any) -> str:
    if isinstance(image_result, dict):
        return str(image_result.get("raw_text", "") or "")
    return str(getattr(image_result, "raw_text", "") or "")


def _has_date_anchor(field: str, raw_text: str) -> bool:
    anchors = DATE_ANCHORS.get(field, ())
    lowered = (raw_text or "").lower()
    return any(anchor in lowered for anchor in anchors)


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _normalize_key(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", _normalize_whitespace(value).upper())


def _normalize_for_field(field: str, value: str) -> str:
    text = _normalize_whitespace(value)
    if not text:
        return ""
    if field == "batch_number":
        return re.sub(r"[\s\-_./]", "", text.upper())
    if field in DATE_FIELDS:
        text = text.replace(".", "/").replace(" ", "")
        match = re.fullmatch(r"(\d{4})[/-](\d{1,2})", text)
        if match:
            return f"{match.group(1)}-{match.group(2).zfill(2)}"
        match = re.fullmatch(r"(\d{1,2})[/-](\d{4})", text)
        if match:
            return f"{match.group(1).zfill(2)}/{match.group(2)}"
        match = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2}|\d{4})", text)
        if match:
            return f"{match.group(1).zfill(2)}/{match.group(2).zfill(2)}/{match.group(3)}"
        return text
    return text


def _canonical_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, _normalize_key(a), _normalize_key(b)).ratio()


def _field_similarity(field: str, a: str, b: str) -> float:
    if field == "medicine_name":
        return max(
            _canonical_similarity(a, b),
            SequenceMatcher(
                None,
                _normalize_whitespace(a).upper(),
                _normalize_whitespace(b).upper(),
            ).ratio(),
        )
    return _canonical_similarity(a, b)


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9\-/\.]*", text or "")


def _image_profile_from_text(raw_text: str, candidate_count: int, ocr_proxy: float) -> str:
    text = (raw_text or "").strip()
    tokens = _tokenize(text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    symbol_chars = sum(1 for ch in text if not ch.isalnum() and not ch.isspace())
    symbol_ratio = symbol_chars / max(len(text), 1)
    if not text or not tokens or symbol_ratio >= 0.42 or ocr_proxy < 0.22:
        return "HEAVY_DISTORTION"
    if ocr_proxy < 0.48 or symbol_ratio >= 0.25 or len(lines) <= 2:
        return "OCR_NOISY"
    if candidate_count <= 1 or len(tokens) < 8:
        return "PARTIAL_LABEL"
    return "CLEAN_SIGNAL"


def _profile_weight(profile: str) -> float:
    return IMAGE_PROFILE_WEIGHTS.get((profile or "HEAVY_DISTORTION").strip().upper(), 0.50)


def _semantic_variance_score(values: List[str]) -> float:
    normalized = [v for v in (_normalize_for_field("medicine_name", value) for value in values) if v]
    if len(normalized) <= 1:
        return 0.0
    pairs = 0
    variance = 0.0
    for i in range(len(normalized)):
        for j in range(i + 1, len(normalized)):
            pairs += 1
            variance += 1.0 - _canonical_similarity(normalized[i], normalized[j])
    return round(variance / max(pairs, 1), 4)


def _noise_ratio(raw_text: str) -> float:
    tokens = _tokenize(raw_text)
    if not tokens:
        return 1.0
    noisy = 0
    for token in tokens:
        alnum = sum(ch.isalnum() for ch in token)
        if len(token) <= 1 or alnum / max(len(token), 1) < 0.6:
            noisy += 1
    return noisy / len(tokens)


def _raw_repetition_count(field: str, candidate: str, raw_text: str) -> int:
    text = raw_text or ""
    if not text or not candidate:
        return 0
    normalized_candidate = _normalize_for_field(field, candidate)
    if not normalized_candidate:
        return 0
    if field == "medicine_name":
        count = 0
        for line in [line.strip() for line in text.splitlines() if line.strip()]:
            if _canonical_similarity(line, normalized_candidate) >= 0.84:
                count += 1
        if count:
            return count
    compact_text = _normalize_key(text)
    compact_candidate = _normalize_key(normalized_candidate)
    if not compact_candidate:
        return 0
    return compact_text.count(compact_candidate)


def _region_score(field: str, region: str | None) -> float:
    region = (region or "full").lower()
    if field == "medicine_name":
        return {"top": 1.0, "middle": 0.55, "bottom": 0.25, "full": 0.45}.get(region, 0.35)
    if field == "manufacturer":
        return {"top": 0.45, "middle": 1.0, "bottom": 0.35, "full": 0.55}.get(region, 0.45)
    if field in DATE_FIELDS | {"batch_number"}:
        return {"top": 0.20, "middle": 0.55, "bottom": 1.0, "full": 0.60}.get(region, 0.45)
    return 0.4


def _is_valid_batch(value: str) -> bool:
    value = _normalize_for_field("batch_number", value)
    if not value:
        return False
    if not 3 <= len(value) <= 20:
        return False
    if not re.fullmatch(r"[A-Z0-9]+", value):
        return False
    if not any(ch.isalpha() for ch in value) or not any(ch.isdigit() for ch in value):
        return False
    return True


def _is_valid_date(value: str) -> bool:
    value = _normalize_for_field("expiry_date", value)
    if not value:
        return False
    return bool(
        re.fullmatch(r"\d{1,2}/\d{4}", value)
        or re.fullmatch(r"\d{4}-\d{2}", value)
        or re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", value)
    )


def _is_plausible_medicine_name(value: str) -> bool:
    value = _normalize_for_field("medicine_name", value)
    if not value or len(value) < 3:
        return False
    if any(hint in value.lower() for hint in ("batch", "expiry", "mfg", "manufact")):
        return False
    digits = sum(ch.isdigit() for ch in value)
    return digits <= max(1, len(value) // 3)


def _is_plausible_manufacturer(value: str) -> bool:
    value = _normalize_for_field("manufacturer", value)
    if not value or len(value) < 3:
        return False
    if any(hint in value.lower() for hint in ("batch", "expiry", "mfg", "tablet", "capsule")):
        return False
    if re.search(r"\b\d{1,2}[/-]\d{2,4}\b", value):
        return False
    return bool(
        re.search(
            r"\b(ltd|limited|pvt|private|labs?|laboratories|pharma|pharmaceuticals?|healthcare|care|inc|corp|company)\.?\b",
            value,
            re.I,
        )
    )


def _format_validity_score(field: str, value: str) -> Tuple[bool, float]:
    value = (value or "").strip()
    if not value:
        return False, 0.0
    if field in DATE_FIELDS:
        normalized = _normalize_for_field(field, value)
        if re.fullmatch(r"\d{4}", normalized):
            return False, 0.0
        if not _is_valid_date(normalized):
            return False, 0.0
        # Dates must be anchored in the raw text to avoid accidental
        # cross-field leakage from isolated numbers.
        return True, 1.0
    if field == "batch_number":
        valid = _is_valid_batch(value)
        return valid, 1.0 if valid else 0.0
    if field == "medicine_name":
        valid = _is_plausible_medicine_name(value)
        return valid, 1.0 if valid else 0.0
    if field == "manufacturer":
        valid = _is_plausible_manufacturer(value)
        return valid, 1.0 if valid else 0.0
    return True, 0.5


def _field_thresholds(field: str) -> Dict[str, float]:
    strict = field in STRICT_FIELDS
    return {
        "support_min": 0.52 if strict else 0.45,
        "strong_min": 0.74 if strict else 0.68,
        "conflict_min": 0.34 if strict else 0.30,
        "similarity": 0.84 if field == "medicine_name" else 0.92,
        "ocr_min": 0.42 if strict else 0.35,
    }


# ============================================================================
# RULE D: FORMAT VALIDATION - Strict regex checks for structured fields
# ============================================================================

def _is_valid_batch_format(value: str) -> bool:
    """Strict batch number format validation."""
    if not value:
        return False
    # Batch: alphanumeric with no pure digits, 3-20 chars
    if not (3 <= len(value) <= 20):
        return False
    if not re.match(r"^[A-Z0-9][A-Z0-9\-/\.]*$", value.strip().upper()):
        return False
    # Must have at least one letter AND one digit
    if not (any(c.isalpha() for c in value) and any(c.isdigit() for c in value)):
        return False
    return True


def _is_valid_date_format(value: str) -> bool:
    """Strict date format validation (MM/YYYY or DD/MM/YYYY)."""
    if not value:
        return False
    value = value.strip()
    # Accepts MM/YYYY, MM-YYYY, MM/YY, or DD/MM/YYYY formats
    if re.match(r"^\d{1,2}[/-]\d{4}$", value):  # MM/YYYY or MM-YYYY
        return True
    if re.match(r"^\d{1,2}[/-]\d{2}$", value):  # MM/YY
        return True
    if re.match(r"^\d{1,2}[/-]\d{1,2}[/-]\d{4}$", value):  # DD/MM/YYYY
        return True
    return False


def _is_valid_medicine_name_format(value: str) -> bool:
    """Medicine name should be text-heavy, minimal digits."""
    if not value:
        return False
    # Should be mostly letters, some dashes/spaces allowed
    alnum = sum(c.isalnum() for c in value)
    if alnum < 4:
        return False
    digit_ratio = sum(c.isdigit() for c in value) / len(value)
    # Reject if too many digits (e.g., "12345678")
    return digit_ratio < 0.5


def _check_format_validity(field: str, value: str) -> bool:
    """Check if a value meets strict format requirements for its field."""
    if not value:
        return True  # empty/None passes format check
    
    value_upper = value.strip().upper()
    
    if field == "batch_number":
        return _is_valid_batch_format(value_upper)
    elif field in ("expiry_date", "mfg_date"):
        return _is_valid_date_format(value)
    elif field == "medicine_name":
        return _is_valid_medicine_name_format(value)
    elif field == "manufacturer":
        # manufacturer: mostly text, no strict format
        return len(value.strip()) >= 3
    
    return True


def _tokenize(text: str) -> List[str]:
    if not text:
        return []
    tokens = re.findall(r"[A-Za-z0-9\-/\.]{1,}", text)
    return [t.strip() for t in tokens if t.strip()]


def _is_noisy_token(token: str) -> bool:
    # heuristic: tokens with many non-alnum or very short
    if not token:
        return True
    if len(token) <= 1:
        return True
    bad = sum(1 for ch in token if not (ch.isalnum() or ch in '/-.'))
    return (bad / max(len(token), 1)) > 0.4


def _normalize(v: str) -> str:
    return (v or "").strip().upper()


def _collect_field_evidence(ocr_output: Any, field: str) -> Tuple[List[Tuple[int, str, float]], float]:
    """Return list of (image_index, value, confidence) and noise_ratio across images."""
    image_results = getattr(ocr_output, "image_results", [])
    evidence = []
    total_tokens = 0
    noisy_tokens = 0
    for idx, imgres in enumerate(image_results, start=1):
        # image_result expected to have attribute named for field with .value and .confidence
        det = getattr(imgres, field, None)
        if det is None:
            continue
        val = det.value
        conf = float(getattr(det, "confidence", 0.0) or 0.0)
        if val and str(val).strip():
            evidence.append((idx, str(val).strip(), conf))
            toks = _tokenize(str(imgres.raw_text))
            total_tokens += len(toks)
            noisy_tokens += sum(1 for t in toks if _is_noisy_token(t))
    noise_ratio = (noisy_tokens / total_tokens) if total_tokens > 0 else 0.0
    return evidence, noise_ratio


def validate_evidence(fusion_output: Any, ocr_output: Any) -> Tuple[Dict[str, FinalField], Dict[str, Any]]:
    """Validate fused fields using strict evidence rules.

    Returns (final_fields, summary)
    summary contains keys: any_rejected (bool), suggestions_for_refusion (dict)
    """
    final_fields: Dict[str, FinalField] = {}
    suggestions_for_refusion: Dict[str, Dict[str, Any]] = {}
    any_rejected = False

    # Build quick map of fused values per field
    fused_map: Dict[str, str] = {}
    for field in CORE_FIELDS:
        fused = getattr(fusion_output, field, None)
        fused_val = None
        if fused is not None:
            fused_val = getattr(fused, "final_value", None)
        fused_map[field] = _normalize(fused_val or "")

    # Validate per field
    for field in CORE_FIELDS:
        fused_val = fused_map.get(field, "")
        evidence, noise_ratio = _collect_field_evidence(ocr_output, field)

        # Start with default FinalField (REJECTED unless proven)
        ff = FinalField(
            value=fused_val or "",
            state="REJECTED",
            confidence_score=0.0,
            rejection_reason="",
            evidence_sources=[],
            validation_flags={
                "evidence_sufficient": False,
                "no_contradiction": False,
                "cross_image_supported": False,
                "noise_within_limit": False,
            },
        )

        # Noise dominance check
        ff.validation_flags["noise_within_limit"] = noise_ratio <= 0.4

        # RULE D: Format correctness check (strict validation for structured fields)
        if fused_val and not _check_format_validity(field, fused_val):
            ff.state = "REJECTED"
            ff.rejection_reason = "INVALID_FORMAT"
            ff.validation_flags["no_contradiction"] = False
            final_fields[field] = ff
            any_rejected = True
            continue

        # If no fused value, it's rejected immediately
        if not fused_val:
            ff.rejection_reason = "NO_FUSED_VALUE"
            final_fields[field] = ff
            any_rejected = True
            continue

        # If evidence empty -> insufficient
        if not evidence:
            ff.rejection_reason = "INSUFFICIENT_EVIDENCE"
            final_fields[field] = ff
            any_rejected = True
            continue

        # Build normalized evidence counts
        norm_counts: Dict[str, List[Tuple[int, float]]] = {}
        for img_idx, val, conf in evidence:
            norm = _normalize(val)
            norm_counts.setdefault(norm, []).append((img_idx, val, conf))

        # If there are >1 distinct normalized values -> contradiction -> reject
        if len(norm_counts) > 1:
            ff.rejection_reason = "EVIDENCE_CONTRADICTION"
            # suggest conflicting variants for removal
            suggestions_for_refusion[field] = {"conflicting_values": list(norm_counts.keys())}
            final_fields[field] = ff
            any_rejected = True
            continue

        # Single normalized candidate exists
        candidate = next(iter(norm_counts.keys()))

        # Check candidate aligns with fused_val
        if candidate != _normalize(fused_val):
            ff.rejection_reason = "FUSION_MISMATCH_WITH_EVIDENCE"
            final_fields[field] = ff
            any_rejected = True
            # Suggest removing the fused value from images that disagree
            suggestions_for_refusion[field] = {"conflicting_values": [candidate]}
            continue

        # Evidence sufficiency: need >=2 independent signals or 1 image + structurally unique
        independent_images = {img_idx for img_idx, _, _ in norm_counts[candidate]}
        if len(independent_images) >= 2:
            ff.validation_flags["evidence_sufficient"] = True
            ff.validation_flags["cross_image_supported"] = True
        else:
            # single-image: check structurally unique: heuristics -> token length and low noise
            single_img_idx = next(iter(independent_images))
            supporting_items = norm_counts[candidate]
            # structural uniqueness heuristic: candidate token length >=4 and appears as distinct token in raw_text
            raw = ""
            try:
                raw = ocr_output.image_results[single_img_idx - 1].raw_text
            except Exception:
                raw = ""
            tokens = _tokenize(raw)
            occ = sum(1 for t in tokens if _normalize(t) == candidate)
            structurally_unique = (len(candidate) >= 4 and occ == 1 and noise_ratio <= 0.25)
            if structurally_unique:
                ff.validation_flags["evidence_sufficient"] = True
                ff.validation_flags["cross_image_supported"] = False
            else:
                ff.rejection_reason = "INSUFFICIENT_INDEPENDENT_EVIDENCE"
                final_fields[field] = ff
                any_rejected = True
                continue

        # All supporting evidence must imply final value (we already normalized and matched candidate)
        # noise dominance
        if not ff.validation_flags["noise_within_limit"]:
            ff.rejection_reason = "NOISE_DOMINANCE"
            final_fields[field] = ff
            any_rejected = True
            continue

        # Passed all checks -> CONFIRMED
        ff.state = "CONFIRMED"
        ff.confidence_score = float(sum(conf for _, _, conf in norm_counts[candidate]) / max(len(norm_counts[candidate]), 1))
        ff.evidence_sources = [{"image_index": i, "value": v, "confidence": c} for i, v, c in norm_counts[candidate]]
        final_fields[field] = ff

    summary = {
        "any_rejected": any_rejected,
        "suggestions_for_refusion": suggestions_for_refusion,
    }
    return final_fields, summary


# ============================================================================
# New deterministic forensic validator
# ============================================================================


def _candidate_records_v2(ocr_output: Any, field: str) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for image_index, image_result in enumerate(_get_image_results(ocr_output), start=1):
        detection = _field_detection(image_result, field)
        if detection is None:
            continue

        raw_value = str(getattr(detection, "raw_value", None) or getattr(detection, "value", None) or "").strip()
        value = str(getattr(detection, "value", None) or raw_value or "").strip()
        if not value:
            continue

        normalized = _normalize_for_field(field, value)
        if not normalized:
            continue

        confidence = max(0.0, min(1.0, float(getattr(detection, "confidence", 0.0) or 0.0)))
        region = str(getattr(detection, "region", None) or "full").lower()
        raw_text = _field_raw_text(image_result)
        has_anchor = _has_date_anchor(field, raw_text) if field in DATE_FIELDS else True
        image_noise = _noise_ratio(raw_text)
        repetition = _raw_repetition_count(field, normalized, raw_text)
        format_valid, format_score = _format_validity_score(field, normalized)
        image_profile = getattr(image_result, "image_profile", None)
        if isinstance(image_result, dict):
            image_profile = image_result.get("image_profile", image_profile)
        image_profile = str(image_profile or _image_profile_from_text(raw_text, 1, confidence)).strip().upper()
        image_profile_score = _profile_weight(image_profile)
        if field in DATE_FIELDS and not has_anchor:
            format_valid = False
            format_score = 0.0

        records.append(
            {
                "image_index": image_index,
                "raw_value": raw_value or value,
                "value": value,
                "normalized": normalized,
                "confidence": confidence,
                "region": region,
                "raw_text": raw_text,
                "has_anchor": bool(has_anchor),
                "noise_ratio": round(image_noise, 4),
                "repetition_count": int(repetition),
                "format_valid": bool(format_valid),
                "format_score": round(format_score, 4),
                "region_score": round(_region_score(field, region), 4),
                "cross_image_support_score": 0.0,
                "region_alignment_score": round(_region_score(field, region), 4),
                "noise_score": round(image_noise, 4),
                "ocr_proxy": round(confidence * (1.0 - image_noise), 4),
                "image_profile": image_profile,
                "image_profile_score": round(float(image_profile_score), 4),
            }
        )
    return records


def _cluster_candidates_v2(field: str, candidates: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    if not candidates:
        return []

    if field == "medicine_name":
        clusters: List[List[Dict[str, Any]]] = []
        for candidate in candidates:
            placed = False
            for cluster in clusters:
                anchor = cluster[0]["normalized"]
                if _field_similarity(field, anchor, candidate["normalized"]) >= 0.84:
                    cluster.append(candidate)
                    placed = True
                    break
            if not placed:
                clusters.append([candidate])
        return clusters

    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate["normalized"]].append(candidate)
    return list(grouped.values())


def _cluster_metrics_v2(field: str, cluster: List[Dict[str, Any]], total_images: int) -> Dict[str, Any]:
    support_images = len({item["image_index"] for item in cluster})
    support_ratio = support_images / max(total_images, 1)
    repetition_total = sum(int(item["repetition_count"]) for item in cluster)
    noise_scores = [float(item["noise_ratio"]) for item in cluster]
    format_scores = [float(item["format_score"]) for item in cluster]
    region_scores = [float(item["region_score"]) for item in cluster]
    conf_scores = [float(item["confidence"]) for item in cluster]
    ocr_proxies = [float(item["ocr_proxy"]) for item in cluster]
    influence_weights = [
        max(
            0.0,
            float(item["confidence"])
            * float(item.get("image_profile_score", 1.0))
            * (1.0 - float(item["noise_ratio"]))
            * (0.6 + 0.4 * float(item["region_score"]))
        )
        for item in cluster
    ]
    total_influence = sum(influence_weights) or 1.0
    influence_shares = [weight / total_influence for weight in influence_weights]
    dominant_influence = max(influence_shares) if influence_shares else 0.0

    best_item = max(
        cluster,
        key=lambda item: (
            float(item["confidence"]),
            float(item["format_score"]),
            float(item["region_score"]),
            float(item["ocr_proxy"]),
            float(item["repetition_count"]),
            -int(item["image_index"]),
        ),
    )

    repetition_score = min(1.0, repetition_total / max(2 if field in STRICT_FIELDS else 1, 1))
    return {
        "support_images": support_images,
        "support_ratio": round(support_ratio, 4),
        "repetition_score": round(repetition_score, 4),
        "format_score": round(max(format_scores) if format_scores else 0.0, 4),
        "region_score": round(max(region_scores) if region_scores else 0.0, 4),
        "ocr_proxy": round(sum(ocr_proxies) / max(len(ocr_proxies), 1), 4),
        "noise_ratio": round(sum(noise_scores) / max(len(noise_scores), 1), 4),
        "confidence_proxy": round(sum(conf_scores) / max(len(conf_scores), 1), 4),
        "cross_image_support_score": round(support_ratio, 4),
        "dominant_image_influence": round(dominant_influence, 4),
        "image_profile_score": round(sum(float(item.get("image_profile_score", 1.0)) for item in cluster) / max(len(cluster), 1), 4),
        "best_item": best_item,
    }


def _combined_cluster_score_v2(field: str, metrics: Dict[str, Any]) -> float:
    thresholds = _field_thresholds(field)
    score = (
        0.27 * min(1.0, metrics["support_ratio"] / max(thresholds["support_min"], 0.01))
        + 0.18 * metrics["format_score"]
        + 0.18 * metrics["region_score"]
        + 0.14 * metrics["repetition_score"]
        + 0.15 * metrics["ocr_proxy"]
        + 0.08 * (1.0 - metrics["noise_ratio"])
    )
    return round(min(1.0, score), 4)


def _failure_mode_from_reason(
    rejection_reason: str,
    *,
    conflict_clusters: int = 0,
    dominant_influence: float = 0.0,
    low_noise_score: float = 0.0,
) -> str:
    if rejection_reason == "FORMAT_INVALID":
        return "FORMAT_VIOLATION"
    if rejection_reason == "CROSS_CONFLICT_BLOCKED" or conflict_clusters > 0:
        return "CONSISTENT_CONFLICT"
    if rejection_reason == "LOW_OCR_CONFIDENCE":
        return "NOISE_FAILURE"
    if dominant_influence > 0.60:
        return "SINGLE_IMAGE_DOMINANCE_BLOCKED"
    if rejection_reason in {"NO_VALID_CANDIDATES", "WEAK_SIGNAL_REJECTED"}:
        if low_noise_score >= 0.55:
            return "NOISE_FAILURE"
        return "INSUFFICIENT_EVIDENCE"
    return "INSUFFICIENT_EVIDENCE"


def _calibrated_confidence(signal_breakdown: Dict[str, Any]) -> float:
    cross_image_support = float(
        signal_breakdown.get(
            "cross_image_support_score",
            signal_breakdown.get("cross_image_agreement", 0.0),
        )
        or 0.0
    )
    format_validity = float(signal_breakdown.get("format_validity_score", 0.0) or 0.0)
    region_alignment = float(
        signal_breakdown.get(
            "region_alignment_score",
            signal_breakdown.get("region_consistency_score", 0.0),
        )
        or 0.0
    )
    noise_score = float(signal_breakdown.get("noise_score", signal_breakdown.get("noise_ratio", 1.0)) or 1.0)
    score = (
        0.35 * cross_image_support
        + 0.25 * format_validity
        + 0.20 * region_alignment
        + 0.20 * (1.0 - noise_score)
    )
    return round(max(0.0, min(1.0, score)), 4)


def _pick_consensus_v2(field: str, clusters: List[List[Dict[str, Any]]], total_images: int) -> Dict[str, Any]:
    thresholds = _field_thresholds(field)
    if not clusters:
        return {
            "value": "",
            "normalized": "",
            "state": "REJECTED",
            "confidence_score": 0.0,
            "rejection_reason": "NO_VALID_CANDIDATES",
            "failure_mode": "INSUFFICIENT_EVIDENCE",
            "evidence_sources": [],
            "signal_breakdown": {
                "signal_availability": {
                    "has_ocr_evidence": False,
                    "has_format_evidence": False,
                    "has_region_evidence": False,
                    "has_repetition_evidence": False,
                    "has_cross_image_evidence": False,
                },
                "cross_image_support_score": 0.0,
                "region_alignment_score": 0.0,
                "format_validity_score": 0.0,
                "noise_score": 0.0,
                "conflict_score": 0.0,
                "semantic_variance_score": 0.0,
                "consistency_stress_score": 0.0,
                "dominant_image_influence": 0.0,
                "single_image_dominance_blocked": False,
                "demo_stability_mode": bool(DEMO_STABILITY_MODE),
                "combined_score": 0.0,
            },
        }

    ranked: List[Dict[str, Any]] = []
    for cluster in clusters:
        metrics = _cluster_metrics_v2(field, cluster, total_images)
        ranked.append(
            {
                "cluster": cluster,
                "metrics": metrics,
                "combined_score": _combined_cluster_score_v2(field, metrics),
                "winner": metrics["best_item"],
            }
        )

    ranked.sort(
        key=lambda item: (
            item["combined_score"],
            item["metrics"]["support_images"],
            item["metrics"]["format_score"],
            item["metrics"]["region_score"],
            item["metrics"]["ocr_proxy"],
            item["metrics"]["repetition_score"],
        ),
        reverse=True,
    )

    best = ranked[0]
    best_metrics = best["metrics"]
    best_normalized = best["winner"]["normalized"]
    conflict_clusters: List[Dict[str, Any]] = []

    for competitor in ranked[1:]:
        comp_metrics = competitor["metrics"]
        similarity = _field_similarity(field, best_normalized, competitor["winner"]["normalized"])
        if similarity < thresholds["similarity"] and competitor["combined_score"] >= thresholds["conflict_min"]:
            conflict_clusters.append(competitor)

    all_normalized_values = sorted(
        {
            cluster["winner"]["normalized"]
            for cluster in ranked
            if cluster["winner"]["normalized"]
        }
    )
    semantic_variance_score = _semantic_variance_score(all_normalized_values)

    cross_image_supported = best_metrics["support_images"] >= 2
    format_valid = best_metrics["format_score"] >= 1.0
    region_supported = best_metrics["region_score"] >= 0.40
    repetition_supported = best_metrics["repetition_score"] >= 0.5
    ocr_confident = best_metrics["ocr_proxy"] >= thresholds["ocr_min"]
    no_conflict = len(conflict_clusters) == 0
    conflict_score = max((item["combined_score"] for item in conflict_clusters), default=0.0)
    noise_score = round(best_metrics["noise_ratio"], 4)
    dominant_influence = best_metrics["dominant_image_influence"]
    single_image_dominance_blocked = total_images > 1 and dominant_influence > 0.60 and best_metrics["support_images"] < 2
    consistency_stress = max(conflict_score, semantic_variance_score)
    strong_structured_evidence = (
        format_valid
        and region_supported
        and repetition_supported
        and ocr_confident
        and no_conflict
        and semantic_variance_score < 0.35
        and best["combined_score"] >= thresholds["strong_min"]
    )
    evidence_sufficient = cross_image_supported or strong_structured_evidence
    low_ocr_confidence = best_metrics["ocr_proxy"] < thresholds["ocr_min"] or best_metrics["noise_ratio"] >= 0.55

    if field == "medicine_name":
        field_plausible = _is_plausible_medicine_name(best["winner"]["value"])
    elif field == "manufacturer":
        field_plausible = _is_plausible_manufacturer(best["winner"]["value"])
    elif field == "batch_number":
        field_plausible = _is_valid_batch(best["winner"]["value"])
    else:
        field_plausible = _is_valid_date(best["winner"]["value"])

    if not field_plausible:
        rejection_reason = "FORMAT_INVALID"
    elif conflict_clusters or (semantic_variance_score >= 0.35 and best_metrics["support_images"] < 2):
        rejection_reason = "CROSS_CONFLICT_BLOCKED"
    elif single_image_dominance_blocked:
        rejection_reason = "WEAK_SIGNAL_REJECTED"
    elif not evidence_sufficient:
        rejection_reason = "LOW_OCR_CONFIDENCE" if low_ocr_confidence else "WEAK_SIGNAL_REJECTED"
    elif low_ocr_confidence and not cross_image_supported:
        rejection_reason = "LOW_OCR_CONFIDENCE"
    else:
        rejection_reason = ""

    evidence_sources = [
        {
            "image_index": item["image_index"],
            "value": item["raw_value"],
            "normalized_value": item["normalized"],
            "confidence": round(float(item["confidence"]), 4),
            "region": item["region"],
            "noise_ratio": round(float(item["noise_ratio"]), 4),
            "repetition_count": int(item["repetition_count"]),
        }
        for item in best["cluster"]
    ]

    signal_breakdown = {
        "signal_availability": {
            "has_ocr_evidence": True,
            "has_format_evidence": format_valid,
            "has_region_evidence": region_supported,
            "has_repetition_evidence": repetition_supported,
            "has_cross_image_evidence": cross_image_supported,
        },
        "field_policy": {
            "strict_field": field in STRICT_FIELDS,
            "requires_two_image_agreement": True,
            "allows_strong_structured_evidence": True,
        },
        "candidate_count": len(best["cluster"]),
        "supporting_image_count": best_metrics["support_images"],
        "conflicting_cluster_count": len(conflict_clusters),
        "cross_image_agreement": round(best_metrics["support_ratio"], 4),
        "cross_image_support_score": round(best_metrics["support_ratio"], 4),
        "format_validity_score": round(best_metrics["format_score"], 4),
        "region_alignment_score": round(best_metrics["region_score"], 4),
        "region_consistency_score": round(best_metrics["region_score"], 4),
        "token_repetition_score": round(best_metrics["repetition_score"], 4),
        "ocr_confidence_proxy": round(best_metrics["ocr_proxy"], 4),
        "noise_score": noise_score,
        "noise_ratio": noise_score,
        "conflict_score": round(conflict_score, 4),
        "semantic_variance_score": round(semantic_variance_score, 4),
        "consistency_stress_score": round(consistency_stress, 4),
        "dominant_image_influence": round(dominant_influence, 4),
        "single_image_dominance_blocked": bool(single_image_dominance_blocked),
        "demo_stability_mode": bool(DEMO_STABILITY_MODE),
        "combined_score": round(best["combined_score"], 4),
        "conflict_values": [competitor["winner"]["value"] for competitor in conflict_clusters],
    }
    signal_breakdown["calibrated_confidence"] = _calibrated_confidence(signal_breakdown)
    signal_breakdown["decision_state"] = "CONFIRMED"

    stable_rejection = (
        conflict_score > REJECTION_CONFLICT_THRESHOLD
        or (not format_valid and not cross_image_supported)
        or (single_image_dominance_blocked and conflict_score > 0.0)
    )
    decision_state = "CONFIRMED"
    if rejection_reason and stable_rejection:
        decision_state = "REJECTED"
    elif rejection_reason:
        decision_state = "WEAK_CONFIRMED"
        rejection_reason = ""

    signal_breakdown["decision_state"] = decision_state

    if decision_state == "REJECTED":
        return {
            "value": "",
            "normalized": best_normalized,
            "state": "REJECTED",
            "confidence_score": 0.0,
            "rejection_reason": rejection_reason,
            "failure_mode": _failure_mode_from_reason(
                rejection_reason,
                conflict_clusters=len(conflict_clusters),
                dominant_influence=dominant_influence,
                low_noise_score=noise_score,
            ),
            "evidence_sources": evidence_sources,
            "signal_breakdown": signal_breakdown,
        }

    return {
        "value": best["winner"]["value"],
        "normalized": best_normalized,
        "state": "CONFIRMED",
        "confidence_score": round(signal_breakdown["calibrated_confidence"], 4),
        "rejection_reason": "",
        "failure_mode": "",
        "evidence_sources": evidence_sources,
        "signal_breakdown": signal_breakdown,
    }


def validate_evidence(fusion_output: Any, ocr_output: Any) -> Tuple[Dict[str, FinalField], Dict[str, Any]]:
    """Deterministic forensic validation using OCR evidence and cross-image consensus."""
    # FORMAT_INVALID is enforced in the consensus helper before confirmation.
    image_results = _get_image_results(ocr_output)
    total_images = len(image_results)
    final_fields: Dict[str, FinalField] = {}
    field_reports: Dict[str, Dict[str, Any]] = {}
    any_rejected = False

    for field in CORE_FIELDS:
        candidates = _candidate_records_v2(ocr_output, field)
        clusters = _cluster_candidates_v2(field, candidates)
        decision = _pick_consensus_v2(field, clusters, total_images)

        fused_obj = getattr(fusion_output, field, None)
        fused_value = str(getattr(fused_obj, "final_value", None) or "").strip()
        fused_normalized = _normalize_for_field(field, fused_value)
        decision_normalized = str(decision.get("normalized", "") or "")

        if decision["state"] == "CONFIRMED" and fused_normalized and fused_normalized != decision_normalized:
            similarity = _field_similarity(field, fused_normalized, decision_normalized)
            if not (field == "medicine_name" and similarity >= 0.84):
                decision = {
                    **decision,
                    "state": "REJECTED",
                    "value": "",
                    "confidence_score": 0.0,
                    "rejection_reason": "CROSS_CONFLICT_BLOCKED",
                    "failure_mode": "CONSISTENT_CONFLICT",
                }

        rejection_reason = str(decision.get("rejection_reason", "") or "")
        if rejection_reason and rejection_reason not in ALLOWED_REJECTION_REASONS:
            rejection_reason = "WEAK_SIGNAL_REJECTED"

        signal_breakdown = dict(decision.get("signal_breakdown", {}))
        evidence_sources = list(decision.get("evidence_sources", []))
        failure_mode = str(decision.get("failure_mode", "") or "")
        if not failure_mode and rejection_reason:
            failure_mode = _failure_mode_from_reason(
                rejection_reason,
                conflict_clusters=int(signal_breakdown.get("conflicting_cluster_count", 0) or 0),
                dominant_influence=float(signal_breakdown.get("dominant_image_influence", 0.0) or 0.0),
                low_noise_score=float(signal_breakdown.get("noise_score", signal_breakdown.get("noise_ratio", 0.0)) or 0.0),
            )

        state = "CONFIRMED" if decision.get("state") == "CONFIRMED" and not rejection_reason else "REJECTED"
        value = str(decision.get("value", "") or "").strip() if state == "CONFIRMED" else ""

        validation_flags = {
            "evidence_sufficient": bool(signal_breakdown.get("cross_image_support_score", signal_breakdown.get("cross_image_agreement", 0.0)) >= 0.5 or signal_breakdown.get("token_repetition_score", 0.0) >= 1.0),
            "no_contradiction": not bool(signal_breakdown.get("conflicting_cluster_count", 0)),
            "cross_image_supported": bool(signal_breakdown.get("supporting_image_count", 0) >= 2),
            "noise_within_limit": bool(signal_breakdown.get("noise_score", signal_breakdown.get("noise_ratio", 1.0)) <= 0.45),
        }

        if state == "REJECTED" and not failure_mode:
            failure_mode = "INSUFFICIENT_EVIDENCE"

        ff = FinalField(
            value=value,
            state=state,
            confidence_score=round(float(decision.get("confidence_score", 0.0) or 0.0), 4) if state == "CONFIRMED" else 0.0,
            rejection_reason="" if state == "CONFIRMED" else (rejection_reason or "WEAK_SIGNAL_REJECTED"),
            failure_mode=failure_mode if state == "REJECTED" else "",
            evidence_sources=evidence_sources,
            signal_breakdown=signal_breakdown,
            validation_flags=validation_flags,
        )

        support_signals = sum(
            1
            for key in (
                "cross_image_support_score",
                "format_validity_score",
                "region_alignment_score",
                "token_repetition_score",
                "semantic_variance_score",
            )
            if float(signal_breakdown.get(key, 0.0) or 0.0) > 0.0
        )
        if ff.state == "CONFIRMED" and support_signals < 1:
            ff.state = "REJECTED"
            ff.value = ""
            ff.confidence_score = 0.0
            ff.rejection_reason = "WEAK_SIGNAL_REJECTED"
            ff.failure_mode = "INSUFFICIENT_EVIDENCE"
        elif ff.state == "REJECTED":
            consolidated_mode = _failure_mode_from_reason(
                ff.rejection_reason or "WEAK_SIGNAL_REJECTED",
                conflict_clusters=int(signal_breakdown.get("conflicting_cluster_count", 0) or 0),
                dominant_influence=float(signal_breakdown.get("dominant_image_influence", 0.0) or 0.0),
                low_noise_score=float(signal_breakdown.get("noise_score", signal_breakdown.get("noise_ratio", 0.0)) or 0.0),
            )
            ff.failure_mode = consolidated_mode or "INSUFFICIENT_EVIDENCE"
        ff.signal_breakdown["decision_state"] = ff.state

        final_fields[field] = ff
        field_reports[field] = {
            "value": ff.value,
            "state": ff.state,
            "confidence_score": ff.confidence_score,
            "rejection_reason": ff.rejection_reason,
            "failure_mode": ff.failure_mode,
            "evidence_sources": ff.evidence_sources,
            "signal_breakdown": ff.signal_breakdown,
            "validation_flags": ff.validation_flags,
        }
        any_rejected = any_rejected or ff.state == "REJECTED"

    total_fields = max(len(CORE_FIELDS), 1)
    rejected_reports = [report for report in field_reports.values() if report.get("state") == "REJECTED"]
    global_conflict_density = round(
        sum(
            1
            for report in rejected_reports
            if str(report.get("failure_mode", "")) == "CONSISTENT_CONFLICT"
        )
        / total_fields,
        4,
    )
    global_noise_density = round(
        sum(
            1
            for report in rejected_reports
            if str(report.get("failure_mode", "")) == "NOISE_FAILURE"
        )
        / total_fields,
        4,
    )
    failure_groups: Dict[str, List[str]] = defaultdict(list)
    for field, report in field_reports.items():
        if report.get("state") == "REJECTED":
            failure_groups[str(report.get("failure_mode", "") or "INSUFFICIENT_EVIDENCE")].append(field)

    system_level_explanation = {}
    for mode, fields in failure_groups.items():
        if len(fields) >= 2:
            system_level_explanation = {
                "root_cause": mode,
                "affected_fields": fields,
                "message": f"{len(fields)} fields rejected due to shared {mode.lower().replace('_', ' ')}.",
            }
            break

    summary = {
        "any_rejected": any_rejected,
        "suggestions_for_refusion": _build_refusion_suggestions_v2(field_reports),
        "field_reports": field_reports,
        "global_conflict_density": global_conflict_density,
        "global_noise_density": global_noise_density,
        "system_level_explanation": system_level_explanation,
        "integrity_check_failed": any(
            report.get("state") == "CONFIRMED" and report.get("confidence_score", 0.0) <= 0.0
            for report in field_reports.values()
        ),
    }
    return final_fields, summary


def _build_refusion_suggestions_v2(field_reports: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    suggestions: Dict[str, Dict[str, Any]] = {}
    for field, report in field_reports.items():
        reason = str(report.get("rejection_reason", "") or "")
        if reason == "NO_VALID_CANDIDATES":
            continue
        if reason in ALLOWED_REJECTION_REASONS:
            suggestions[field] = {
                "conflicting_values": [
                    str(item.get("normalized_value") or item.get("value") or "")
                    for item in report.get("evidence_sources", [])
                    if str(item.get("normalized_value") or item.get("value") or "").strip()
                ]
            }
    return suggestions
