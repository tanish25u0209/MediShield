from modules.fusion import FIELDS


def compute_confidence(num_images: int, fused_fields: dict, mismatch_count: int, total_issues: int) -> float:
    completeness = sum(1 for field in FIELDS if fused_fields.get(field)) / len(FIELDS)
    image_factor = min(1.0, num_images / 3.0)
    mismatch_penalty = min(0.5, mismatch_count * 0.08)
    issue_penalty = min(0.5, total_issues * 0.04)

    raw_score = (0.45 * completeness + 0.55 * image_factor) - mismatch_penalty - issue_penalty
    return max(0.0, min(100.0, round(raw_score * 100.0, 2)))
