SEVERITY_WEIGHTS = {"low": 5.0, "medium": 12.0, "high": 25.0}


def _score_issues(issues: list[dict]) -> float:
    score = 0.0
    for issue in issues:
        score += SEVERITY_WEIGHTS.get(issue.get("severity", "low"), 5.0)
    return score


def compute_risk(
    validation_issues: list[dict],
    consistency_issues: list[dict],
    anomaly_issues: list[dict],
    vision_issues: list[dict],
) -> float:
    validation_score = _score_issues(validation_issues) * 1.1
    consistency_score = _score_issues(consistency_issues) * 0.9
    anomaly_score = _score_issues(anomaly_issues) * 1.0
    vision_score = _score_issues(vision_issues) * 0.7

    total = validation_score + consistency_score + anomaly_score + vision_score
    return max(0.0, min(100.0, round(total, 2)))
