"""
MediShield Risk Engine Layer
============================
Converts OCR outputs, validation results, fusion conflicts, and classifier
predictions into a structured risk assessment with full explainability.

Architecture:
  Stage 1 — Signal Engineering    : Raw inputs → normalized 0–1 signals
  Stage 2 — Weighted Risk Model   : Signals → composite risk score (0–100)
  Stage 3 — Status Mapping        : Score → Safe / Suspicious / High Risk
  Stage 4 — Confidence Engine     : Meta-signals → Low / Medium / High
  Stage 5 — Explanation Engine    : Signals → human-readable explanations
  Stage 6 — Output Assembly       : Structured JSON-compatible dict

Author : MediShield Backend Team
Version: 1.0.0
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# ──────────────────────────── CONFIGURATION ────────────────────────────────
# ---------------------------------------------------------------------------

# Weights for the risk model.  Must sum to 1.0.
# Rationale documented alongside each weight in RiskWeights below.
RISK_WEIGHTS: dict[str, float] = {
    "consistency":  0.30,   # Cross-image agreement — highest weight; physical
                            # tampering always produces conflicts
    "validation":   0.25,   # Hard rule violations (expired, missing fields)
    "ocr_reliability": 0.20,# Low OCR quality degrades every other signal
    "classifier":   0.15,   # Packaging anomaly from vision model
    "qr_mismatch":  0.10,   # QR↔label discrepancy — strong tamper signal
                            # (downweighted because QR is often absent)
}

assert abs(sum(RISK_WEIGHTS.values()) - 1.0) < 1e-9, "Weights must sum to 1.0"

# Status thresholds (applied to raw 0–100 risk score)
THRESHOLDS = {
    "safe":        (0,  35),   # Low risk — minor noise expected from OCR
    "suspicious":  (35, 65),   # Ambiguous — human review recommended
    "high_risk":   (65, 100),  # Strong anomaly signals present
}

# Validation issue severity mapping
ISSUE_SEVERITY: dict[str, float] = {
    # Critical — directly endangers patient
    "expired":                   1.0,
    "expiry_date_invalid":        1.0,
    "missing_expiry":             0.9,
    "missing_batch":              0.7,
    "batch_format_invalid":       0.6,
    "missing_manufacturer":       0.5,
    "dose_out_of_range":          0.8,
    # Moderate — degrades traceability
    "missing_drug_name":          0.6,
    "missing_composition":        0.4,
    "barcode_unreadable":         0.3,
    # Low — cosmetic / optional fields
    "missing_storage_conditions": 0.2,
    "missing_country_of_origin":  0.1,
}

DEFAULT_ISSUE_SEVERITY = 0.35   # fallback for unknown issue types


# ---------------------------------------------------------------------------
# ──────────────────────────── DATA STRUCTURES ──────────────────────────────
# ---------------------------------------------------------------------------

@dataclass
class RawSignals:
    """Normalized 0–1 risk signals.  Higher value = MORE risk."""
    consistency:      float = 0.0   # 0 = perfectly consistent, 1 = major conflicts
    validation:       float = 0.0   # 0 = no issues, 1 = critical issues present
    ocr_unreliability: float = 0.0  # 0 = high OCR confidence, 1 = very low
    classifier_risk:  float = 0.0   # 0 = confident known class, 1 = anomaly/uncertain
    qr_mismatch:      float = 0.0   # 0 = no QR conflict, 1 = clear mismatch
    qr_available:     bool  = False

@dataclass
class DebugSignals:
    """Full breakdown for developer / audit use."""
    raw:              RawSignals = field(default_factory=RawSignals)
    weighted_components: dict[str, float] = field(default_factory=dict)
    image_count:      int   = 1
    agreement_score:  float = 1.0
    ocr_confidence:   float = 1.0
    conflict_count:   int   = 0
    issue_count:      int   = 0
    classifier_class: str   = "unknown"
    classifier_conf:  float = 0.0

@dataclass
class RiskResult:
    risk_score:   int
    status:       str
    confidence:   str
    explanation:  list[str]
    debug_signals: dict[str, Any]


# ---------------------------------------------------------------------------
# ──────────────────────── STAGE 1: SIGNAL ENGINEERING ──────────────────────
# ---------------------------------------------------------------------------

def compute_consistency_signal(conflicts: list[dict]) -> tuple[float, int]:
    """
    Consistency signal — captures cross-image field disagreement.

    Formula:
        raw_penalty = Σ conflict_weight(severity)
        consistency = clip(raw_penalty / MAX_PENALTY, 0, 1)

    Conflict severity tiers:
        critical fields  (batch, expiry, drug_name) → weight 1.0
        important fields (manufacturer, dose)       → weight 0.6
        minor fields     (storage, country)          → weight 0.3

    MAX_PENALTY = 3.0  (3 critical conflicts saturates the signal)

    Rationale: A single batch-number conflict is a stronger tamper signal
    than five storage-condition conflicts.  Severity weighting prevents
    minor OCR noise from inflating risk.
    """
    FIELD_SEVERITY: dict[str, float] = {
        "batch_number":   1.0, "expiry_date": 1.0, "drug_name": 1.0,
        "manufacturer":   0.6, "dose":        0.6, "composition": 0.5,
        "barcode":        0.4, "storage":     0.3, "country":    0.2,
    }
    MAX_PENALTY = 3.0

    if not conflicts:
        return 0.0, 0

    total_penalty = 0.0
    for conflict in conflicts:
        field_name = str(conflict.get("field", "")).lower()
        # Partial-match lookup
        severity = next(
            (v for k, v in FIELD_SEVERITY.items() if k in field_name),
            0.35  # unknown field default
        )
        total_penalty += severity

    score = min(total_penalty / MAX_PENALTY, 1.0)
    return round(score, 4), len(conflicts)


def compute_validation_signal(issues: list[str | dict]) -> float:
    """
    Validation signal — captures hard-rule violations.

    Formula:
        issue_score_i = ISSUE_SEVERITY.get(issue_key, DEFAULT)
        aggregated    = 1 - Π (1 - issue_score_i)   [probabilistic union]

    Probabilistic union prevents two low-severity issues from adding to 1.0
    while ensuring any single critical issue (severity=1.0) saturates.

    Normalization: result already in [0, 1].
    """
    if not issues:
        return 0.0

    complement = 1.0
    for issue in issues:
        key = (issue if isinstance(issue, str) else issue.get("type", "")).lower()
        severity = ISSUE_SEVERITY.get(key, DEFAULT_ISSUE_SEVERITY)
        complement *= (1.0 - severity)

    return round(1.0 - complement, 4)


def compute_ocr_reliability_signal(ocr_confidence: float) -> float:
    """
    OCR unreliability signal.

    Raw OCR confidence is typically in [0, 1] (e.g. from Tesseract/EasyOCR).
    We invert it so HIGH confidence → LOW risk signal.

    Formula:
        unreliability = 1 - clip(ocr_confidence, 0, 1)

    A soft knee is applied: confidence < 0.3 is treated as near-zero quality
    and mapped to unreliability ≥ 0.85 via a slight exponential boost.
    This prevents the model from tolerating very noisy OCR quietly.
    """
    conf = max(0.0, min(1.0, float(ocr_confidence)))

    if conf < 0.3:
        # Boost penalty for very low confidence: maps [0, 0.3] → [1.0, 0.85]
        boost = 0.85 + (0.3 - conf) / 0.3 * 0.15
        return round(min(boost, 1.0), 4)

    return round(1.0 - conf, 4)


def compute_classifier_signal(predicted_class: str, confidence: float) -> float:
    """
    Classifier risk signal — derived from packaging anomaly detector output.

    Logic:
        1. If predicted_class is a known-legitimate class AND confidence is high
           → low risk signal
        2. If confidence is low (model is uncertain) → moderate risk
        3. If predicted_class is an anomaly/unknown class → elevated risk

    Formula:
        base_risk = 1 - clip(confidence, 0, 1)
        anomaly_boost = 0.3  if class is flagged anomalous
        signal = clip(base_risk + anomaly_boost, 0, 1)

    Rationale: Classifier uncertainty alone is not a hard risk indicator
    (packaging may look unusual for legitimate reasons), but when combined
    with other signals it contributes meaningfully.
    """
    ANOMALY_CLASSES = {"anomaly", "unknown", "damaged", "tampered", "counterfeit"}

    conf = max(0.0, min(1.0, float(confidence)))
    base_risk = 1.0 - conf

    anomaly_boost = 0.3 if str(predicted_class).lower() in ANOMALY_CLASSES else 0.0
    signal = min(base_risk + anomaly_boost, 1.0)

    return round(signal, 4)


def compute_qr_signal(qr_data: dict | None) -> tuple[float, bool]:
    """
    QR mismatch signal.

    Returns (signal_value, qr_available).

    If QR data is absent → signal = 0.0 (not penalized, just unavailable).
    If QR scanned but matches OCR fields → 0.0
    If QR scanned, partial match → 0.3
    If QR scanned, full mismatch → 1.0

    Formula:
        match_ratio = matched_fields / total_qr_fields
        signal      = 1 - match_ratio   (clipped to [0, 1])
    """
    if not qr_data:
        return 0.0, False

    match_status = str(qr_data.get("match_status", "unknown")).lower()

    MATCH_MAP = {
        "full_match":    0.0,
        "partial_match": 0.35,
        "no_match":      1.0,
        "error":         0.5,
        "unknown":       0.3,
    }

    # Fine-grained: use match_ratio if provided
    if "match_ratio" in qr_data:
        ratio = max(0.0, min(1.0, float(qr_data["match_ratio"])))
        return round(1.0 - ratio, 4), True

    return MATCH_MAP.get(match_status, 0.3), True


# ---------------------------------------------------------------------------
# ──────────────────────── STAGE 2: WEIGHTED RISK MODEL ─────────────────────
# ---------------------------------------------------------------------------

def compute_risk_score(signals: RawSignals) -> tuple[int, dict[str, float]]:
    """
    Composite risk score using weighted linear combination.

    Risk Score = Σ weight_i × signal_i  ×  100

    If QR is unavailable, its weight is redistributed proportionally
    to the remaining signals so weights always sum to 1.0.

    Returns:
        risk_score (int, 0–100)
        weighted_components (dict — each signal's contribution)
    """
    weights = dict(RISK_WEIGHTS)

    if not signals.qr_available:
        # Redistribute QR weight proportionally to active signals
        qr_w = weights.pop("qr_mismatch")
        active_total = sum(weights.values())
        for k in weights:
            weights[k] += qr_w * (weights[k] / active_total)

    components = {
        "consistency":      weights.get("consistency", 0)      * signals.consistency,
        "validation":       weights.get("validation", 0)        * signals.validation,
        "ocr_reliability":  weights.get("ocr_reliability", 0)   * signals.ocr_unreliability,
        "classifier":       weights.get("classifier", 0)        * signals.classifier_risk,
        "qr_mismatch":      weights.get("qr_mismatch", 0)       * signals.qr_mismatch,
    }

    raw_score = sum(components.values())          # in [0, 1]
    risk_score = int(round(min(raw_score * 100, 100)))

    weighted_components = {k: round(v * 100, 2) for k, v in components.items()}
    return risk_score, weighted_components


# ---------------------------------------------------------------------------
# ────────────────────────── STAGE 3: STATUS MAPPING ────────────────────────
# ---------------------------------------------------------------------------

def map_status(risk_score: int) -> str:
    """
    Threshold-based status classification.

    Thresholds rationale:
        0–34  (Safe):        Noise-tolerant lower band. Real-world OCR rarely
                             produces perfect 0 scores; this absorbs minor
                             field-level OCR artefacts without alarming users.

        35–64 (Suspicious):  Ambiguous zone — one significant signal tripped
                             (e.g. low OCR + one validation issue).  Flags for
                             human review without condemning the product.

        65–100 (High Risk):  Multiple signals fired or one critical signal
                             (e.g. expiry conflict, classifier anomaly).
                             Strong intervention recommended.

    The wide Suspicious band is intentional: it is cheaper to review a
    borderline product than to miss a tampered one.
    """
    if risk_score <= 34:
        return "Safe"
    elif risk_score <= 64:
        return "Suspicious"
    else:
        return "High Risk"


# ---------------------------------------------------------------------------
# ──────────────────────── STAGE 4: CONFIDENCE ENGINE ───────────────────────
# ---------------------------------------------------------------------------

def compute_confidence(
    image_count: int,
    agreement_score: float,
    ocr_confidence: float,
) -> str:
    """
    Confidence in the risk assessment itself (not in the product).

    Formula:
        image_factor    = clip((image_count - 1) / 4, 0, 1)   → saturates at 5 images
        agreement_factor = clip(agreement_score, 0, 1)
        ocr_factor       = clip(ocr_confidence, 0, 1)

        composite = 0.3×image_factor + 0.4×agreement_factor + 0.3×ocr_factor

    Thresholds:
        ≥ 0.70 → High    (strong evidence base)
        ≥ 0.40 → Medium  (adequate but incomplete)
        < 0.40 → Low     (limited evidence — treat result with caution)

    image_count weight rationale: More images reduce single-scan error.
    agreement_score weight: Highest weight — if images disagree, we genuinely
    don't know ground truth.
    ocr_confidence: Low OCR quality limits all downstream reasoning.
    """
    image_factor    = min((image_count - 1) / 4.0, 1.0)
    agreement_factor = max(0.0, min(1.0, float(agreement_score)))
    ocr_factor       = max(0.0, min(1.0, float(ocr_confidence)))

    composite = (
        0.30 * image_factor +
        0.40 * agreement_factor +
        0.30 * ocr_factor
    )

    if composite >= 0.70:
        return "High"
    elif composite >= 0.40:
        return "Medium"
    else:
        return "Low"


# ---------------------------------------------------------------------------
# ──────────────────────── STAGE 5: EXPLANATION ENGINE ──────────────────────
# ---------------------------------------------------------------------------

def generate_explanations(
    signals:          RawSignals,
    conflicts:        list[dict],
    issues:           list[str | dict],
    ocr_confidence:   float,
    classifier_class: str,
    classifier_conf:  float,
    image_count:      int,
    qr_data:          dict | None,
) -> list[str]:
    """
    Rule-based explanation generator.

    Each signal threshold triggers a specific, actionable explanation.
    Explanations are ordered by severity (most critical first) so that
    the first item is always the most important finding.
    """
    explanations: list[tuple[float, str]] = []   # (severity, message)

    # ── Validation issues ──────────────────────────────────────────────────
    for issue in issues:
        key = (issue if isinstance(issue, str) else issue.get("type", "")).lower()
        sev = ISSUE_SEVERITY.get(key, DEFAULT_ISSUE_SEVERITY)

        MESSAGES: dict[str, str] = {
            "expired":                   "⚠ Medicine is past its expiry date.",
            "expiry_date_invalid":        "⚠ Expiry date format is invalid or unreadable.",
            "missing_expiry":             "⚠ Expiry date is absent from all scanned images.",
            "missing_batch":              "⚠ Batch number could not be found on packaging.",
            "batch_format_invalid":       "⚠ Batch number format does not match expected pattern.",
            "missing_manufacturer":       "ℹ Manufacturer name is missing.",
            "dose_out_of_range":          "⚠ Dosage value is outside the expected safe range.",
            "missing_drug_name":          "⚠ Drug name is not readable.",
            "missing_composition":        "ℹ Composition/ingredient list is absent.",
            "barcode_unreadable":         "ℹ Barcode could not be decoded.",
            "missing_storage_conditions": "ℹ Storage conditions not specified.",
            "missing_country_of_origin":  "ℹ Country of origin not detected.",
        }
        msg = MESSAGES.get(key, f"ℹ Validation issue detected: '{key}'.")
        explanations.append((sev, msg))

    # ── Cross-image conflicts ──────────────────────────────────────────────
    if conflicts:
        critical_fields = [
            c.get("field", "unknown") for c in conflicts
            if any(f in str(c.get("field", "")).lower()
                   for f in ["batch", "expiry", "drug"])
        ]
        if critical_fields:
            fields_str = ", ".join(set(critical_fields))
            explanations.append((
                0.95,
                f"🔴 Critical field mismatch across images: {fields_str}. "
                "This may indicate label tampering."
            ))
        else:
            explanations.append((
                0.5,
                f"🟡 Minor field inconsistencies detected across {len(conflicts)} "
                "fields. Could be OCR noise."
            ))

    # ── OCR Reliability ───────────────────────────────────────────────────
    if ocr_confidence < 0.30:
        explanations.append((
            0.75,
            f"🔴 Very low OCR confidence ({ocr_confidence:.0%}). "
            "Text extraction is unreliable; results may be inaccurate."
        ))
    elif ocr_confidence < 0.55:
        explanations.append((
            0.45,
            f"🟡 Moderate OCR confidence ({ocr_confidence:.0%}). "
            "Some fields may be misread."
        ))

    # ── Classifier signal ─────────────────────────────────────────────────
    ANOMALY_CLASSES = {"anomaly", "unknown", "damaged", "tampered", "counterfeit"}
    if str(classifier_class).lower() in ANOMALY_CLASSES:
        explanations.append((
            0.80,
            f"🔴 Packaging classifier flagged the image as '{classifier_class}' "
            f"(confidence {classifier_conf:.0%}). Visual anomaly detected."
        ))
    elif classifier_conf < 0.50:
        explanations.append((
            0.40,
            f"🟡 Classifier is uncertain about packaging type "
            f"(predicted '{classifier_class}', confidence {classifier_conf:.0%})."
        ))

    # ── QR mismatch ───────────────────────────────────────────────────────
    if qr_data:
        status = str(qr_data.get("match_status", "")).lower()
        if status == "no_match":
            explanations.append((
                1.0,
                "🔴 QR code data does NOT match printed label fields. "
                "Strong indicator of label substitution or tampering."
            ))
        elif status == "partial_match":
            explanations.append((
                0.60,
                "🟡 QR code data partially matches the label. "
                "Some fields are inconsistent."
            ))
    else:
        explanations.append((
            0.05,
            "ℹ No QR code data available; QR verification skipped."
        ))

    # ── Image count warning ───────────────────────────────────────────────
    if image_count == 1:
        explanations.append((
            0.20,
            "ℹ Only one image was provided. "
            "Cross-image verification is unavailable; confidence is reduced."
        ))

    # Sort by severity descending, return messages only
    explanations.sort(key=lambda x: x[0], reverse=True)
    return [msg for _, msg in explanations]


# ---------------------------------------------------------------------------
# ──────────────────────────── EDGE CASE GUARDS ─────────────────────────────
# ---------------------------------------------------------------------------

def _sanitize_inputs(
    ocr_output:         dict,
    classifier_output:  dict,
) -> tuple[list, list, float, str, float, dict | None, float, int]:
    """
    Normalizes and sanitizes all inputs.
    Returns:
        conflicts, issues, ocr_confidence, predicted_class, classifier_conf,
        qr_data, agreement_score, image_count
    """
    conflicts_raw    = ocr_output.get("conflicts", []) or []
    issues_raw       = ocr_output.get("validation", []) or []
    ocr_confidence   = float(ocr_output.get("ocr_confidence", 0.5))
    qr_data          = ocr_output.get("qr_data", None)

    # Derived parameters may contain agreement score and image count
    derived          = ocr_output.get("derived_parameters", {}) or {}
    agreement_score  = float(derived.get("agreement_score",
                              ocr_output.get("agreement_score", 1.0)))
    image_count      = int(derived.get("image_count",
                          ocr_output.get("image_count", 1)))

    predicted_class  = str(classifier_output.get("predicted_class", "unknown"))
    classifier_conf  = float(classifier_output.get("confidence", 0.5))

    conflicts: list[dict] = []
    for item in conflicts_raw:
        if isinstance(item, dict):
            conflicts.append(item)
            continue
        text = str(item)
        field_name = text.split(" mismatch", 1)[0].strip().lower()
        conflicts.append({"field": field_name, "type": "mismatch", "details": text})

    if isinstance(issues_raw, dict):
        issues = issues_raw.get("issues", []) or []
    elif isinstance(issues_raw, list):
        issues = issues_raw
    else:
        issues = [issues_raw] if issues_raw else []

    # Clamp numeric values
    ocr_confidence  = max(0.0, min(1.0, ocr_confidence))
    agreement_score = max(0.0, min(1.0, agreement_score))
    classifier_conf = max(0.0, min(1.0, classifier_conf))
    image_count     = max(1, image_count)

    return (conflicts, issues, ocr_confidence,
            predicted_class, classifier_conf,
            qr_data, agreement_score, image_count)


# ---------------------------------------------------------------------------
# ─────────────────────────── MAIN PUBLIC API ───────────────────────────────
# ---------------------------------------------------------------------------

def run_risk_engine(
    ocr_output:        dict,
    classifier_output: dict,
    include_debug:     bool = True,
) -> dict:
    """
    Main entry point for the MediShield Risk Engine.

    Parameters
    ----------
    ocr_output : dict
        Output from the OCR + fusion pipeline.  Expected keys:
            final_data, per_image_data, derived_parameters,
            validation, conflicts, ocr_confidence,
            agreement_score (optional), image_count (optional),
            qr_data (optional)

    classifier_output : dict
        Output from the MobileNetV2 packaging classifier.  Expected keys:
            predicted_class, confidence

    include_debug : bool
        If True, includes a detailed debug_signals block in output.

    Returns
    -------
    dict with keys:
        risk_score    (int,  0–100)
        status        (str,  'Safe' | 'Suspicious' | 'High Risk')
        confidence    (str,  'Low' | 'Medium' | 'High')
        explanation   (list of str)
        debug_signals (dict, only if include_debug=True)
    """

    # ── Sanitize inputs ───────────────────────────────────────────────────
    (conflicts, issues, ocr_confidence,
     predicted_class, classifier_conf,
     qr_data, agreement_score, image_count) = _sanitize_inputs(
        ocr_output, classifier_output
    )

    # ── Stage 1: Compute signals ──────────────────────────────────────────
    consistency_score, conflict_count = compute_consistency_signal(conflicts)
    validation_score                  = compute_validation_signal(issues)
    ocr_unreliability                 = compute_ocr_reliability_signal(ocr_confidence)
    classifier_risk                   = compute_classifier_signal(predicted_class, classifier_conf)
    qr_signal, qr_available           = compute_qr_signal(qr_data)

    signals = RawSignals(
        consistency       = consistency_score,
        validation        = validation_score,
        ocr_unreliability = ocr_unreliability,
        classifier_risk   = classifier_risk,
        qr_mismatch       = qr_signal,
        qr_available      = qr_available,
    )

    # ── Stage 2: Risk score ───────────────────────────────────────────────
    risk_score, weighted_components = compute_risk_score(signals)

    # ── Stage 3: Status ───────────────────────────────────────────────────
    status = map_status(risk_score)

    # ── Stage 4: Confidence ───────────────────────────────────────────────
    confidence = compute_confidence(image_count, agreement_score, ocr_confidence)

    # ── Stage 5: Explanations ─────────────────────────────────────────────
    explanation = generate_explanations(
        signals, conflicts, issues, ocr_confidence,
        predicted_class, classifier_conf, image_count, qr_data,
    )

    # ── Stage 6: Assemble output ──────────────────────────────────────────
    result: dict[str, Any] = {
        "risk_score":  risk_score,
        "status":      status,
        "confidence":  confidence,
        "explanation": explanation,
    }

    if include_debug:
        result["debug_signals"] = {
            "raw_signals": {
                "consistency_risk":  signals.consistency,
                "validation_risk":   signals.validation,
                "ocr_unreliability": signals.ocr_unreliability,
                "classifier_risk":   signals.classifier_risk,
                "qr_mismatch":       signals.qr_mismatch,
                "qr_available":      signals.qr_available,
            },
            "weighted_contributions_to_100": weighted_components,
            "meta": {
                "image_count":       image_count,
                "agreement_score":   agreement_score,
                "ocr_confidence":    ocr_confidence,
                "conflict_count":    conflict_count,
                "issue_count":       len(issues),
                "classifier_class":  predicted_class,
                "classifier_conf":   classifier_conf,
            },
            "weights_used": RISK_WEIGHTS,
            "thresholds":   THRESHOLDS,
        }

    return result


# ---------------------------------------------------------------------------
# ──────────────────────────── EXAMPLE WALKTHROUGH ──────────────────────────
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    print("=" * 68)
    print("  MediShield Risk Engine — Example Walkthroughs")
    print("=" * 68)

    # ── Example 1: Clearly Safe Product ──────────────────────────────────
    ocr_safe = {
        "final_data":          {"drug_name": "Paracetamol 500mg", "batch_number": "BT-2025-001"},
        "per_image_data":      [{}, {}],
        "derived_parameters":  {"agreement_score": 0.97, "image_count": 3},
        "validation":          [],
        "conflicts":           [],
        "ocr_confidence":      0.92,
        "qr_data":             {"match_status": "full_match"},
    }
    clf_safe = {"predicted_class": "blister_pack", "confidence": 0.93}

    result_safe = run_risk_engine(ocr_safe, clf_safe)
    print("\n[EXAMPLE 1] Clean product, 3 images, high OCR, no conflicts")
    print(json.dumps(result_safe, indent=2))

    # ── Example 2: Suspicious Product ────────────────────────────────────
    ocr_suspicious = {
        "final_data":          {"drug_name": "Amoxicillin", "batch_number": "XX-??"},
        "per_image_data":      [{}, {}],
        "derived_parameters":  {"agreement_score": 0.70, "image_count": 2},
        "validation":          ["missing_manufacturer", "barcode_unreadable"],
        "conflicts":           [{"field": "batch_number", "values": ["BT-001", "BT-002"]}],
        "ocr_confidence":      0.58,
        "qr_data":             {"match_status": "partial_match"},
    }
    clf_suspicious = {"predicted_class": "blister_pack", "confidence": 0.61}

    result_sus = run_risk_engine(ocr_suspicious, clf_suspicious)
    print("\n[EXAMPLE 2] Suspicious: batch conflict, low OCR, partial QR match")
    print(json.dumps(result_sus, indent=2))

    # ── Example 3: High Risk Product ─────────────────────────────────────
    ocr_high_risk = {
        "final_data":          {"drug_name": "Insulin", "batch_number": "INS-9X"},
        "per_image_data":      [{}, {}],
        "derived_parameters":  {"agreement_score": 0.40, "image_count": 2},
        "validation":          ["expired", "missing_batch", "dose_out_of_range"],
        "conflicts":           [
            {"field": "expiry_date",  "values": ["2023-01", "2025-06"]},
            {"field": "drug_name",    "values": ["Insulin", "Insu1in"]},
            {"field": "batch_number", "values": ["INS-9X", "INS-8Y"]},
        ],
        "ocr_confidence":      0.28,
        "qr_data":             {"match_status": "no_match"},
    }
    clf_high_risk = {"predicted_class": "tampered", "confidence": 0.82}

    result_hr = run_risk_engine(ocr_high_risk, clf_high_risk)
    print("\n[EXAMPLE 3] High Risk: expired, QR mismatch, tampered class, conflicts")
    print(json.dumps(result_hr, indent=2))

    # ── Example 4: Edge Case — Single image, no QR, very low OCR ─────────
    ocr_edge = {
        "final_data":         {},
        "per_image_data":     [{}],
        "derived_parameters": {},
        "validation":         ["missing_expiry", "missing_batch"],
        "conflicts":          [],
        "ocr_confidence":     0.18,
        "qr_data":            None,
    }
    clf_edge = {"predicted_class": "unknown", "confidence": 0.34}

    result_edge = run_risk_engine(ocr_edge, clf_edge)
    print("\n[EXAMPLE 4] Edge: single image, no QR, very low OCR, unknown classifier")
    print(json.dumps(result_edge, indent=2))
