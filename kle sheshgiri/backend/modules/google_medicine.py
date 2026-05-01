from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import httpx

MODEL_NAME = "gemini-2.5-flash"
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent"
CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "google_medicine_cache.json"


def _api_key() -> str | None:
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def _load_cache() -> Dict[str, Dict[str, Any]]:
    if not CACHE_PATH.exists():
        return {}
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cache(cache: Dict[str, Dict[str, Any]]) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _normalize(name: str | None) -> str:
    return " ".join((name or "").strip().lower().replace("-", " ").split())


@lru_cache(maxsize=256)
def fetch_medicine_profile(name: str) -> Dict[str, Any]:
    query = _normalize(name)
    if not query:
        return {}

    cache = _load_cache()
    if query in cache:
        return dict(cache[query])

    api_key = _api_key()
    if not api_key:
        return {}

    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "generic_name": {"type": ["string", "null"]},
            "therapeutic_class": {"type": ["string", "null"]},
            "uses": {"type": "array", "items": {"type": "string"}},
            "conditions_treated": {"type": "array", "items": {"type": "string"}},
            "assistant_summary": {"type": "string"},
            "risks": {"type": "array", "items": {"type": "string"}},
            "reference_sources": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["name", "uses", "conditions_treated", "assistant_summary", "risks", "reference_sources"],
    }

    prompt = f"""
Use Google Search grounding and return a factual medicine profile for: {name}

Rules:
- Keep the name specific to the user input.
- If it is a brand name, include the generic name when known.
- Focus on diseases/conditions treated.
- Include concise risks or important cautions.
- Return only valid JSON matching the schema.
""".strip()

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": schema,
        },
    }

    try:
        response = httpx.post(
            API_URL,
            headers={
                "x-goog-api-key": api_key,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        text = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )
        parsed = json.loads(text) if text else {}
        if not isinstance(parsed, dict):
            return {}
        parsed.setdefault("name", name)
        parsed.setdefault("uses", [])
        parsed.setdefault("conditions_treated", parsed.get("uses", []))
        parsed.setdefault("assistant_summary", "")
        parsed.setdefault("risks", [])
        parsed.setdefault("reference_sources", [])
        cache[query] = parsed
        _save_cache(cache)
        return parsed
    except Exception:
        return {}
