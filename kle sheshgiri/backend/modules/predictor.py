from typing import Dict, List, Optional
import json
import re
from pathlib import Path

# Minimal fallback if parsing fails
_FALLBACK_MEDICINES = [
    {"name": "Paracetamol", "aliases": ["acetaminophen"], "usedFor": "Fever and pain.", "diseaseArea": ["Fever", "Pain"], "caution": "Avoid overdose."}
]


def _load_medicines_from_js() -> List[Dict]:
    """Load `predictor/DEMO/app.js` medicines array verbatim when possible.

    This function extracts the `const medicines = [...]` block and converts it
    to JSON with a targeted, low-risk transformation (quote keys, remove
    trailing commas). The original author data is preserved.
    """
    try:
        js_path = Path(__file__).resolve().parents[2] / "predictor" / "DEMO" / "app.js"
        text = js_path.read_text(encoding="utf-8")
    except Exception:
        return []

    m = re.search(r"const\s+medicines\s*=\s*(\[[\s\S]*?\]);", text)
    if not m:
        return []

    array_text = m.group(1)

    # Quote unquoted keys (basic heuristic): { name: -> { "name":
    def _quote_keys(s: str) -> str:
        return re.sub(r'(?P<prefix>[{,\n\s])(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*:', lambda mo: f"{mo.group('prefix')}\"{mo.group('key')}\":", s)

    json_like = _quote_keys(array_text)

    # Remove trailing commas before closing } or ]
    json_like = re.sub(r",\s*([}\]])", r"\1", json_like)

    # Replace JS undefined with null
    json_like = json_like.replace("undefined", "null")

    try:
        data = json.loads(json_like)
        if isinstance(data, list):
            return data
    except Exception:
        return []

    return []


# Load medicines (prefer user file)
_MEDICINES = _load_medicines_from_js() or _FALLBACK_MEDICINES


def _normalize(value: Optional[str]) -> str:
    if not value:
        return ""
    s = value.lower()
    s = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in s)
    s = " ".join(s.split())
    return s


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i]
        for j, cb in enumerate(b, start=1):
            insert = curr[j - 1] + 1
            delete = prev[j] + 1
            replace = prev[j - 1] + (0 if ca == cb else 1)
            curr.append(min(insert, delete, replace))
        prev = curr
    return prev[-1]


def _score_medicine(query: str, medicine: Dict) -> float:
    q = _normalize(query)
    if not q:
        return 0.0
    targets = [_normalize(medicine.get("name", ""))] + [_normalize(a) for a in medicine.get("aliases", [])]
    best = 0.0
    for target in targets:
        if not target:
            continue
        if target == q:
            best = max(best, 1.0)
        if target in q or q in target:
            best = max(best, 0.86)
        dist = _levenshtein(q, target)
        similarity = 1.0 - dist / max(len(q), len(target)) if max(len(q), len(target)) > 0 else 0.0
        best = max(best, similarity)
    return best


def find_medicine(query: str) -> Dict:
    q = _normalize(query)
    if not q:
        return {"medicine": None, "score": 0.0, "suggestions": []}
    ranked = []
    for med in _MEDICINES:
        score = _score_medicine(q, med)
        ranked.append({"medicine": med, "score": score})
    ranked.sort(key=lambda x: x["score"], reverse=True)
    best = ranked[0]
    suggestions = [item["medicine"].get("name") for item in ranked[:3]]
    if best["score"] >= 0.62:
        return {"medicine": best["medicine"], "score": best["score"], "suggestions": suggestions}
    return {"medicine": None, "score": 0.0, "suggestions": suggestions}
