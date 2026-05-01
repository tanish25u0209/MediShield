from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import Any, Dict

import httpx

XAI_API_URL = "https://api.x.ai/v1/chat/completions"
DEFAULT_MODEL = "grok-4.20-reasoning"


def _api_key() -> str | None:
    return os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY")


def _extract_json(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {}
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        raw = raw[start : end + 1]
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


@lru_cache(maxsize=128)
def fetch_medicine_profile(name: str) -> Dict[str, Any]:
    api_key = _api_key()
    if not api_key:
        return {}

    medicine = (name or "").strip()
    if not medicine:
        return {}

    prompt = f"""
You are a medicine information assistant.
Return ONLY valid JSON for the medicine below.

Medicine: {medicine}

JSON schema:
{{
  "name": string,
  "generic_name": string or null,
  "therapeutic_class": string or null,
  "uses": [string, ...],
  "conditions_treated": [string, ...],
  "assistant_summary": string,
  "risks": [string, ...],
  "reference_sources": [string, ...]
}}

Rules:
- Keep the medicine name specific to the user input.
- If the input is a brand name, include the generic name when known.
- Use concise disease/condition phrases.
- Include only medically relevant uses.
- Put source URLs in reference_sources when possible.
- Do not add markdown, code fences, or commentary.
""".strip()

    payload = {
        "model": DEFAULT_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "You provide concise, factual medicine reference data in strict JSON.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }

    try:
        response = httpx.post(
            XAI_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=25.0,
        )
        response.raise_for_status()
        data = response.json()
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        parsed = _extract_json(content)
        if not parsed:
            return {}

        parsed.setdefault("name", medicine)
        parsed.setdefault("uses", [])
        parsed.setdefault("conditions_treated", parsed.get("uses", []))
        parsed.setdefault("risks", [])
        parsed.setdefault("reference_sources", [])
        return parsed
    except Exception:
        return {}
