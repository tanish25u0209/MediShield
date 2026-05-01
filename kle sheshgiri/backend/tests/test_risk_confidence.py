from modules.confidence import compute_confidence
from modules.risk import compute_risk


def test_risk_scoring_bounds() -> None:
    score = compute_risk(
        validation_issues=[{"severity": "high"}],
        consistency_issues=[{"severity": "medium"}],
        anomaly_issues=[{"severity": "high"}],
        vision_issues=[{"severity": "low"}],
    )
    assert 0 <= score <= 100


def test_confidence_scoring_bounds() -> None:
    score = compute_confidence(
        num_images=3,
        fused_fields={
            "medicine_name": "A",
            "batch_number": "B",
            "mfg_date": "01-01-2025",
            "exp_date": "01-01-2028",
            "manufacturer": "M",
        },
        mismatch_count=0,
        total_issues=0,
    )
    assert 0 <= score <= 100
