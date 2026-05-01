from collections import Counter
from typing import Literal

from modules.normalizer import normalize_field

FIELDS = ["medicine_name", "batch_number", "mfg_date", "exp_date", "manufacturer"]


def _field_strength(value: str) -> int:
    return sum(2 if ch.isalnum() else 1 for ch in value)


def _choose_by_quality_then_deterministic(candidates: list[dict]) -> tuple[dict, Literal["fallback_quality", "fallback_deterministic"]]:
    top_quality = max(item["quality"] for item in candidates)
    quality_best = [item for item in candidates if item["quality"] == top_quality]
    if len(quality_best) == 1:
        return quality_best[0], "fallback_quality"

    quality_best.sort(key=lambda item: (-item["strength"], item["display"], item["source_index"]))
    return quality_best[0], "fallback_deterministic"


def _source_quality(index: int, quality_signals: list[dict] | None) -> float:
    if not quality_signals or index >= len(quality_signals):
        return 50.0

    quality = quality_signals[index] or {}
    score = 50.0
    blur = float(quality.get("blur_score", 0.0))
    score += min(30.0, blur / 20.0)
    if quality.get("is_blurry"):
        score -= 15.0
    if quality.get("is_low_quality"):
        score -= 12.0
    if quality.get("is_distorted"):
        score -= 8.0
    return score


def _pick_field_value(field: str, extractions: list[dict], quality_signals: list[dict] | None) -> tuple[str | None, dict]:
    candidates: list[dict] = []

    for index, extraction in enumerate(extractions):
        normalized = normalize_field(field, extraction.get(field))
        if not normalized:
            continue

        display, vote_key = normalized
        candidates.append(
            {
                "display": display,
                "vote_key": vote_key,
                "source_index": index,
                "quality": _source_quality(index, quality_signals),
                "strength": _field_strength(display),
            }
        )

    if not candidates:
        return None, {
            "selected": None,
            "votes": {},
            "candidates": [],
            "conflict": False,
            "source_index": None,
            "chosen_by": "no_candidates",
        }

    vote_counter = Counter(item["vote_key"] for item in candidates)
    max_count = max(vote_counter.values())
    top_keys = [key for key, count in vote_counter.items() if count == max_count]

    key_winners: list[dict] = []
    for key in top_keys:
        key_candidates = [item for item in candidates if item["vote_key"] == key]
        key_candidates.sort(key=lambda item: (-item["quality"], -item["strength"], item["source_index"], item["display"]))
        key_winners.append(
            {
                "vote_key": key,
                "count": vote_counter[key],
                "winner": key_candidates[0],
            }
        )

    chosen_by: str = "majority"
    if len(top_keys) == 1:
        selected = key_winners[0]["winner"]
    else:
        tie_candidates = [item["winner"] for item in key_winners]
        selected, chosen_by = _choose_by_quality_then_deterministic(tie_candidates)

    votes: dict[str, int] = {}
    display_by_key: dict[str, str] = {}
    for candidate in sorted(candidates, key=lambda item: (item["vote_key"], item["display"])):
        display_by_key.setdefault(candidate["vote_key"], candidate["display"])
    for key, count in vote_counter.items():
        votes[display_by_key.get(key, key)] = count

    candidates_view = [item["display"] for item in sorted(candidates, key=lambda item: (item["source_index"], item["display"]))]

    meta = {
        "selected": selected["display"],
        "votes": votes,
        "candidates": candidates_view,
        "conflict": len(vote_counter) > 1,
        "source_index": selected["source_index"],
        "chosen_by": chosen_by,
    }
    return selected["display"], meta


def fuse_data_with_meta(extractions: list[dict], quality_signals: list[dict] | None = None) -> tuple[dict, dict]:
    fused: dict = {}
    fusion_meta: dict = {}
    for field in FIELDS:
        fused[field], fusion_meta[field] = _pick_field_value(field, extractions, quality_signals)
    return fused, fusion_meta


def fuse_data(extractions: list[dict], quality_signals: list[dict] | None = None) -> dict:
    fused, _ = fuse_data_with_meta(extractions, quality_signals)
    return fused
