from modules.fusion import FIELDS


def check_consistency(extractions: list[dict], fused: dict) -> tuple[list[dict], int]:
    issues = []
    mismatch_count = 0

    for field in FIELDS:
        expected = fused.get(field)
        values = {entry.get(field) for entry in extractions if entry.get(field)}
        if expected and len(values) > 1:
            mismatch_count += 1
            issues.append(
                {
                    "code": f"mismatch_{field}",
                    "message": f"Mismatch detected in {field.replace('_', ' ')} across images",
                    "severity": "medium",
                }
            )

    return issues, mismatch_count
