from datetime import date

from dateutil import parser


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return parser.parse(value, dayfirst=True).date()
    except Exception:
        return None


def validate_fields(fields: dict) -> list[dict]:
    issues: list[dict] = []
    today = date.today()

    if not fields.get("medicine_name"):
        issues.append({"code": "missing_medicine_name", "message": "Medicine name could not be detected", "severity": "medium"})

    mfg = _parse_date(fields.get("mfg_date"))
    exp = _parse_date(fields.get("exp_date"))

    if fields.get("mfg_date") and not mfg:
        issues.append({"code": "invalid_mfg_date", "message": "Manufacturing date format is invalid", "severity": "medium"})

    if fields.get("exp_date") and not exp:
        issues.append({"code": "invalid_exp_date", "message": "Expiry date format is invalid", "severity": "medium"})

    if mfg and mfg > today:
        issues.append({"code": "future_mfg_date", "message": "Manufacturing date is in the future", "severity": "high"})

    if exp and exp < today:
        issues.append({"code": "expired_product", "message": "Product is expired", "severity": "high"})

    if mfg and exp and mfg > exp:
        issues.append({"code": "mfg_after_exp", "message": "Manufacturing date is after expiry date", "severity": "high"})

    return issues
