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

from copy import deepcopy
import re
from typing import Dict, Any, List, Tuple

from pipeline_schemas import FinalField


CORE_FIELDS = ["medicine_name", "batch_number", "expiry_date", "mfg_date", "manufacturer"]


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
