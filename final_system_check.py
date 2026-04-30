#!/usr/bin/env python3
"""Final forensic verification for the OCR + fusion contract."""

from __future__ import annotations

import json

from medishield_ocr import process_medicine_images


FORENSIC_EVAL_PROMPT = """
You are a forensic medicine packaging extraction engine.
You do NOT guess. You do NOT infer missing data. You do NOT complete partial information.
Only extract what is explicitly supported by OCR evidence across multiple signals.
Hard OCR contract: exactly 2 OCR stages per image, no additional OCR calls, no confidence-based skipping.
Forbidden behavior: invent missing values, normalize unclear text into valid-looking fields, fill missing fields using heuristics, promote single-image evidence, resolve conflicts without cross-image agreement, treat noisy OCR tokens as valid structured data.
Strict fields: batch_number, expiry_date, mfg_date. Relaxed fields: medicine_name, manufacturer. Output requires value, state, confidence_score, rejection_reason, evidence_sources.
"""


def _enforce_forensic_contract(result: dict) -> list[str]:
    violations: list[str] = []
    per_image_calls = [int(trace.get("ocr_calls", 0) or 0) for trace in result.get("ocr_traces", [])]
    if any(count != 2 for count in per_image_calls):
        violations.append("OCR contract violated: per-image OCR calls are not exactly 2")
    if not all(bool(trace.get("stage_1_used")) for trace in result.get("ocr_traces", [])):
        violations.append("OCR contract violated: stage_1_used is not true for all images")
    if not all(bool(trace.get("stage_2_used")) for trace in result.get("ocr_traces", [])):
        violations.append("OCR contract violated: stage_2_used is not true for all images")

    field_decisions = result.get("field_decisions", {}) or {}
    truth_validation = result.get("truth_validation", {}) or {}
    core_fields = ["medicine_name", "batch_number", "expiry_date", "mfg_date", "manufacturer"]
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
    return violations


def _collect_three_images() -> list[str]:
    from pathlib import Path

    candidates = sorted(Path("samples").rglob("*.jpg"))
    if len(candidates) < 3:
        candidates = sorted(Path("medishield_data").rglob("*.jpg"))
    return [str(path) for path in candidates[:3]]


def main() -> int:
    print("[FINAL FORENSIC VERIFICATION]")
    print("=" * 70)
    print(FORENSIC_EVAL_PROMPT.strip())
    print("=" * 70)

    images = _collect_three_images()
    if len(images) < 3:
        print("[FAIL] Need at least 3 sample images for verification")
        return 1

    result = process_medicine_images(images)

    field_decisions = result.get("field_decisions", {}) or {}
    truth_validation = result.get("truth_validation", {}) or {}
    print(json.dumps(
        {
            "images": images,
            "ocr": {
                "OCR_calls_count": result.get("OCR_calls_count", 0),
                "stage_1_used": result.get("stage_1_used", False),
                "stage_2_used": result.get("stage_2_used", False),
                "per_image_ocr_calls": [int(trace.get("ocr_calls", 0) or 0) for trace in result.get("ocr_traces", [])],
            },
            "field_decisions": field_decisions,
            "truth_validation": truth_validation,
            "evidence": result.get("evidence", {}),
        },
        indent=2,
    ))

    violations = _enforce_forensic_contract(result)
    if violations:
        print("[FAIL]")
        for violation in violations:
            print(f"- {violation}")
        return 1

    print("[PASS] OCR contract and forensic decision contract verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
