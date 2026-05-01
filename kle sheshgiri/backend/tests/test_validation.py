from modules.validation import validate_fields


def test_validation_expired_product() -> None:
    issues = validate_fields({"mfg_date": "01-01-2020", "exp_date": "01-01-2021"})
    codes = {issue["code"] for issue in issues}
    assert "expired_product" in codes


def test_validation_invalid_dates() -> None:
    issues = validate_fields({"mfg_date": "not-a-date", "exp_date": "also-bad"})
    codes = {issue["code"] for issue in issues}
    assert "invalid_mfg_date" in codes
    assert "invalid_exp_date" in codes
