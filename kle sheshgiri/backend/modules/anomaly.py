import json
from pathlib import Path


def load_batch_data(path: str) -> dict:
    file_path = Path(path)
    if not file_path.exists():
        return {}
    with file_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def detect_anomalies(
    fused_fields: dict,
    recent_scan_count: int,
    batch_data: dict,
    observed_cities: list[str] | None = None,
) -> list[dict]:
    issues: list[dict] = []
    batch = fused_fields.get("batch_number")
    observed_cities = [city.strip() for city in (observed_cities or []) if city and city.strip()]

    if recent_scan_count >= 8:
        issues.append(
            {
                "code": "burst_scans",
                "message": "Unusually high number of recent scans detected",
                "severity": "high",
            }
        )

    if batch and batch in batch_data and observed_cities:
        allowed = {city.lower() for city in batch_data[batch]}
        seen = {city.lower() for city in observed_cities}
        if len(seen) > 1:
            issues.append(
                {
                    "code": "multiple_cities",
                    "message": "Same batch appears across multiple cities",
                    "severity": "high",
                }
            )
        if not seen.issubset(allowed):
            issues.append(
                {
                    "code": "unknown_city_pattern",
                    "message": "Observed city does not match expected batch distribution",
                    "severity": "medium",
                }
            )

    if batch and batch not in batch_data:
        issues.append(
            {
                "code": "batch_not_found",
                "message": "Batch not found in simulation intelligence data",
                "severity": "low",
            }
        )

    return issues
