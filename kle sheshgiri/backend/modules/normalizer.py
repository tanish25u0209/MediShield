from typing import Any

from dateutil import parser

PLACEHOLDERS = {"", "na", "n/a", "none", "null", "unknown", "-"}


def clean_text(value: Any) -> str:
    return " ".join(str(value).strip().split())


def is_invalid(value: Any) -> bool:
    if value is None:
        return True
    cleaned = clean_text(value).lower()
    return cleaned in PLACEHOLDERS


def normalize_name(value: Any) -> str | None:
    if is_invalid(value):
        return None
    return clean_text(value)


def normalize_batch(value: Any) -> str | None:
    if is_invalid(value):
        return None
    return clean_text(value).upper().replace(" ", "")


def normalize_date(value: Any) -> str | None:
    if is_invalid(value):
        return None

    try:
        parsed = parser.parse(clean_text(value), dayfirst=True)
    except Exception:
        return None
    return parsed.date().isoformat()


def normalize_field(field: str, value: Any) -> tuple[str, str] | None:
    if field in {"medicine_name", "manufacturer", "name"}:
        normalized = normalize_name(value)
        if not normalized:
            return None
        return normalized, normalized.casefold()

    if field in {"batch_number", "batch"}:
        normalized = normalize_batch(value)
        if not normalized:
            return None
        return normalized, normalized

    if field in {"mfg_date", "exp_date", "mfg", "exp"}:
        normalized = normalize_date(value)
        if not normalized:
            return None
        return normalized, normalized

    if is_invalid(value):
        return None

    normalized = clean_text(value)
    return normalized, normalized.casefold()
