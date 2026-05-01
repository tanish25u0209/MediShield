from typing import Any

import cv2

try:
    from pyzbar.pyzbar import decode as pyzbar_decode
except Exception:  # pragma: no cover
    pyzbar_decode = None


def _parse_payload(payload: str) -> dict:
    data = {}
    normalized = payload.replace("\n", ";")
    for part in normalized.split(";"):
        if ":" in part:
            key, value = part.split(":", 1)
            data[key.strip().lower()] = value.strip()
    return data


def scan_codes(image: Any) -> tuple[list[str], dict]:
    payloads: list[str] = []
    parsed: dict = {}

    if pyzbar_decode is not None:
        decoded = pyzbar_decode(image)
        for item in decoded:
            try:
                payload = item.data.decode("utf-8", errors="ignore").strip()
            except Exception:
                payload = ""
            if payload:
                payloads.append(payload)

    detector = cv2.QRCodeDetector()
    value, _, _ = detector.detectAndDecode(image)
    if value:
        payloads.append(value.strip())

    for payload in payloads:
        parsed.update(_parse_payload(payload))

    return payloads, parsed
