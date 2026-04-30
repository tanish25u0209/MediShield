#!/usr/bin/env python3
"""Three-sample end-to-end verification for the single-entry OCR pipeline."""

from __future__ import annotations

import json
from pathlib import Path

from medishield_pipeline import process_medicine


FORENSIC_EVAL_PROMPT = """
You are a forensic medicine packaging extraction engine.
You do NOT guess. You do NOT infer missing data. You do NOT complete partial information.
Only extract what is explicitly supported by OCR evidence across multiple signals.
Hard OCR contract: exactly 2 OCR stages per image, no additional OCR calls, no confidence-based skipping.
Forbidden behavior: invent missing values, normalize unclear text into valid-looking fields, fill missing fields using heuristics, promote single-image evidence, resolve conflicts without cross-image agreement, treat noisy OCR tokens as valid structured data.
Strict fields: batch_number, expiry_date, mfg_date. Relaxed fields: medicine_name, manufacturer. Output requires value, state, confidence_score, rejection_reason, evidence_sources.
"""


def _collect_three_images() -> list[str]:
    candidates = sorted(Path("samples").rglob("*.jpg"))
    if len(candidates) < 3:
        candidates = sorted(Path("medishield_data").rglob("*.jpg"))
    return [str(path) for path in candidates[:3]]


def main() -> int:
    images = _collect_three_images()
    if len(images) < 3:
        print("Need at least 3 sample images for the verification run.")
        return 1

    result = process_medicine(images)
    ocr = result.get("ocr", {}) or {}
    field_decisions = ocr.get("field_decisions", {}) or {}
    truth_validation = ocr.get("truth_validation", {}) or {}
    per_image_calls = [int(trace.get("ocr_calls", 0) or 0) for trace in ocr.get("ocr_traces", [])]
    violations = [count for count in per_image_calls if count != 2]
    contract_violations = _enforce_forensic_contract(ocr, field_decisions, truth_validation)

    payload = {
        "forensic_eval_prompt": FORENSIC_EVAL_PROMPT.strip(),
        "images": images,
        "raw_text": ocr.get("raw_text", ""),
        "confidence": ocr.get("confidence", 0.0),
        "fallback_used": ocr.get("fallback_used", False),
        "OCR_calls_count": ocr.get("OCR_calls_count", 0),
        "stage_1_used": ocr.get("stage_1_used", False),
        "stage_2_used": ocr.get("stage_2_used", False),
        "tokens_extracted": ocr.get("tokens_extracted", 0),
        "unique_tokens": ocr.get("unique_tokens", 0),
        "tesseract_calls_count": sum(int(trace.get("tesseract_calls", 0) or 0) for trace in ocr.get("ocr_traces", [])),
        "per_image_ocr_calls": [
            int(trace.get("ocr_calls", 0) or 0) for trace in ocr.get("ocr_traces", [])
        ],
        "per_image_fallback_used": [
            bool(trace.get("fallback_triggered")) for trace in ocr.get("ocr_traces", [])
        ],
        "extracted_fields": ocr.get("final_data", {}),
        "field_decisions": field_decisions,
        "truth_validation": truth_validation,
        "evidence": ocr.get("evidence", {}),
        "risk_result": result.get("risk", {}),
    }

    print(json.dumps(payload, indent=2))
    if not ocr.get("stage_1_used", False) or not ocr.get("stage_2_used", False) or violations or contract_violations:
        print(
            "Verification failed: "
            f"OCR call budget violations={len(violations)}, "
            f"forensic violations={len(contract_violations)}."
        )
        return 1
    return 0


def _enforce_forensic_contract(ocr: dict, field_decisions: dict, truth_validation: dict) -> list[str]:
    violations: list[str] = []
    core_fields = ["medicine_name", "batch_number", "expiry_date", "mfg_date", "manufacturer"]
    strict_fields = {"batch_number", "expiry_date", "mfg_date"}

    for field_name in core_fields:
        decision = field_decisions.get(field_name, {}) or {}
        flags = truth_validation.get(field_name, {}) or {}
        value = str(decision.get("value", "") or "").strip()
        state = str(decision.get("state", "") or "").strip()
        reason = str(decision.get("rejection_reason", "") or "").strip()
        evidence_sources = decision.get("evidence_sources", []) or []

        if value and state != "CONFIRMED":
            violations.append(f"{field_name}: non-empty value must be CONFIRMED")
        if not value and state not in {"REJECTED", "EMPTY"}:
            violations.append(f"{field_name}: empty value must be REJECTED or EMPTY")
        if state == "CONFIRMED" and not evidence_sources:
            violations.append(f"{field_name}: CONFIRMED requires evidence sources")
        if state == "REJECTED" and not reason:
            violations.append(f"{field_name}: REJECTED requires rejection reason")
        for flag_name in ("evidence_sufficient", "no_contradiction", "cross_image_supported", "noise_within_limit"):
            if flag_name not in flags:
                violations.append(f"{field_name}: missing truth-validation flag {flag_name}")
        if field_name in strict_fields and value and len(evidence_sources) == 1:
            violations.append(f"{field_name}: strict field should not rely on single-source support")
    return violations


if __name__ == "__main__":
    raise SystemExit(main())
