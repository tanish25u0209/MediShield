"""
Google Gemini fallback integration for MediShield.
Used when OCR confidence is low, fields are missing, or conflicts exist.
"""

import base64
import json
import os
from typing import Optional

import google.generativeai as genai


def init_gemini() -> None:
    """Initialize Gemini API with key from environment."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable not set")
    genai.configure(api_key=api_key)


def should_use_gemini_fallback(
    ocr_confidence: float,
    parsed_fields: dict,
    validation_issues: list,
    consistency_issues: list,
) -> bool:
    """
    Determine if Gemini fallback should be triggered.
    
    Args:
        ocr_confidence: Confidence score (0-100) from OCR
        parsed_fields: Extracted field data
        validation_issues: List of validation errors
        consistency_issues: List of consistency mismatches
    
    Returns:
        True if fallback should be used
    """
    # Trigger if confidence is low
    if ocr_confidence < 50:
        return True
    
    # Trigger if critical fields are missing
    critical_fields = ["medicine_name", "batch_number", "expiry_date"]
    missing = [f for f in critical_fields if not parsed_fields.get(f)]
    if missing:
        return True
    
    # Trigger if significant validation issues
    if len(validation_issues) > 2:
        return True
    
    # Trigger if consistency conflicts exist
    if consistency_issues:
        return True
    
    return False


def encode_image_to_base64(image_bytes: bytes) -> str:
    """Encode image bytes to base64 string."""
    return base64.standard_b64encode(image_bytes).decode("utf-8")


def extract_fields_with_gemini(
    front_image_bytes: bytes,
    back_image_bytes: Optional[bytes] = None,
    barcode_image_bytes: Optional[bytes] = None,
) -> dict:
    """
    Extract medicine fields using Google Gemini vision model.
    
    Args:
        front_image_bytes: Front of medicine package image
        back_image_bytes: Back of package (optional)
        barcode_image_bytes: QR/barcode image (optional)
    
    Returns:
        Dict with extracted fields and metadata
    """
    init_gemini()
    
    model = genai.GenerativeModel("gemini-2.0-flash")
    
    # Build request with image parts
    parts = []
    
    # Add front image
    parts.append({
        "mime_type": "image/jpeg",
        "data": encode_image_to_base64(front_image_bytes),
    })
    
    if back_image_bytes:
        parts.append({
            "mime_type": "image/jpeg",
            "data": encode_image_to_base64(back_image_bytes),
        })
    
    if barcode_image_bytes:
        parts.append({
            "mime_type": "image/jpeg",
            "data": encode_image_to_base64(barcode_image_bytes),
        })
    
    # Main extraction prompt
    extraction_prompt = """You are analyzing medicine packaging images.

Read all uploaded images carefully and extract only factual visible information.

Find these fields:
- medicine_name
- brand_name
- dosage_strength
- dosage_form
- batch_number
- manufacturing_date
- expiry_date
- manufacturer_name
- mrp_price
- composition
- license_number
- barcode_number
- qr_text

Rules:
1. Use only text visible in images.
2. If unclear, return null.
3. Do not guess hidden text.
4. Normalize dates to MM/YYYY if possible.
5. If multiple values appear, return the most likely one and mention conflicts.

Return output in clean JSON only, no markdown, no explanation."""
    
    parts.append(extraction_prompt)
    
    # Call Gemini
    response = model.generate_content(parts)
    
    # Parse response
    try:
        response_text = response.text.strip()
        # Remove markdown code blocks if present
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
        
        extracted = json.loads(response_text)
    except (json.JSONDecodeError, AttributeError) as e:
        extracted = {
            "error": f"Failed to parse Gemini response: {str(e)}",
            "raw_response": response.text if response else "No response",
        }
    
    return {
        "source": "gemini_fallback",
        "fields": extracted,
        "confidence": 75,  # Gemini fallback confidence
        "model": "gemini-2.0-flash",
    }


def resolve_field_conflicts(
    source_a: dict,
    source_b: dict,
    source_c: Optional[dict] = None,
    conflict_fields: Optional[list] = None,
) -> dict:
    """
    Resolve conflicts between multiple extraction sources using Gemini.
    
    Args:
        source_a: First source (e.g., OCR front)
        source_b: Second source (e.g., OCR back)
        source_c: Third source (optional, e.g., Gemini)
        conflict_fields: List of field names with conflicts
    
    Returns:
        Dict with resolved fields and confidence
    """
    init_gemini()
    
    model = genai.GenerativeModel("gemini-2.0-flash")
    
    if not conflict_fields:
        conflict_fields = ["batch_number", "expiry_date", "medicine_name"]
    
    # Build conflict summary
    conflict_data = {
        "Source A (OCR Front)": {f: source_a.get(f) for f in conflict_fields},
        "Source B (OCR Back)": {f: source_b.get(f) for f in conflict_fields},
    }
    if source_c:
        conflict_data["Source C (Gemini)"] = {f: source_c.get(f) for f in conflict_fields}
    
    conflict_prompt = f"""Three sources extracted conflicting medicine data.

{json.dumps(conflict_data, indent=2)}

Determine the most likely correct values based on:
1. OCR typo patterns (e.g., O vs 0, l vs 1)
2. Consistency across sources
3. Common packaging logic (e.g., batch format, date ranges)

For each conflicting field, return:
- final_value: Most likely correct value
- reason: Why this value was chosen
- confidence: 0-100 confidence in this choice

Return as clean JSON only."""
    
    response = model.generate_content(conflict_prompt)
    
    try:
        response_text = response.text.strip()
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
        
        resolved = json.loads(response_text)
    except (json.JSONDecodeError, AttributeError):
        resolved = {"error": "Failed to resolve conflicts"}
    
    return resolved


def generate_risk_explanations(validation_issues: list, consistency_issues: list, anomaly_issues: list) -> list:
    """
    Generate user-friendly risk explanations using Gemini.
    
    Args:
        validation_issues: List of validation issue dicts
        consistency_issues: List of consistency mismatch dicts
        anomaly_issues: List of anomaly detection issues
    
    Returns:
        List of user-friendly explanation strings
    """
    init_gemini()
    
    model = genai.GenerativeModel("gemini-2.0-flash")
    
    all_issues = validation_issues + consistency_issues + anomaly_issues
    issue_types = [issue.get("code", "unknown") for issue in all_issues]
    
    explanation_prompt = f"""Given these validation and consistency issues found in medicine verification:

Issues: {json.dumps(issue_types[:10], indent=2)}

Write short, user-friendly bullet-point explanations (2-3 words each) for why each is a concern.

Rules:
1. Use simple language
2. Avoid claiming fake medicine directly
3. Use risk language like "mismatch", "unreadable", "inconsistent"
4. Each bullet: issue_type | reason

Return as JSON list of strings only."""
    
    response = model.generate_content(explanation_prompt)
    
    try:
        response_text = response.text.strip()
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
        
        explanations = json.loads(response_text)
    except (json.JSONDecodeError, AttributeError):
        explanations = ["Unable to generate explanations"]
    
    return explanations if isinstance(explanations, list) else ["Unable to parse explanations"]


def generate_summary(
    risk_score: float,
    confidence: float,
    issues: list,
) -> str:
    """
    Generate concise user-facing summary using Gemini.
    
    Args:
        risk_score: Medicine risk score (0-100)
        confidence: Verification confidence (0-100)
        issues: List of issue codes
    
    Returns:
        3-line user-facing summary
    """
    init_gemini()
    
    model = genai.GenerativeModel("gemini-2.0-flash")
    
    # Determine risk level
    if risk_score >= 70:
        risk_level = "High Risk"
    elif risk_score >= 30:
        risk_level = "Suspicious"
    else:
        risk_level = "Safe"
    
    summary_prompt = f"""Summarize this medicine verification result in exactly 2-3 lines.

Risk Score: {risk_score}
Risk Level: {risk_level}
Confidence: {confidence}%
Issues: {json.dumps(issues[:5], indent=2)}

Rules:
1. Use simple language for general users
2. Do not claim certainty ("appears to" not "is")
3. Focus on actionable info
4. 2-3 sentences max

Return as plain text only."""
    
    response = model.generate_content(summary_prompt)
    
    summary = response.text.strip() if response else "Unable to generate summary"
    return summary


# Example usage for integration:
"""
# In main.py scan endpoint, after computing confidence/issues:

if should_use_gemini_fallback(confidence, fused, validation_issues, consistency_issues):
    gemini_result = extract_fields_with_gemini(front_image_bytes, back_image_bytes)
    # Merge or use Gemini-extracted fields to enhance confidence
    
    explanations = generate_risk_explanations(
        validation_issues, consistency_issues, anomaly_issues
    )
    
    summary = generate_summary(risk_score, confidence, all_issues)
"""
