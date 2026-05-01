#!/usr/bin/env python3
"""Test the /scan API endpoint without external HTTP dependencies."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageDraw


API_URL = os.environ.get("MEDISHIELD_API_URL", "http://127.0.0.1:8000").strip() or "http://127.0.0.1:8000"


def _post_json(path: str, payload: dict) -> tuple[int, str]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{API_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.status, response.read().decode("utf-8")


def _post_multipart(path: str, files: list[tuple[str, str, str, bytes]]) -> tuple[int, str]:
    boundary = "----MediShieldBoundary" + uuid4().hex
    body = BytesIO()
    for field, filename, content_type, content in files:
        body.write(f"--{boundary}\r\n".encode())
        body.write(f"Content-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\n".encode())
        body.write(f"Content-Type: {content_type}\r\n\r\n".encode())
        body.write(content)
        body.write(b"\r\n")
    body.write(f"--{boundary}--\r\n".encode())
    request = urllib.request.Request(
        f"{API_URL}{path}",
        data=body.getvalue(),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status, response.read().decode("utf-8")


if __name__ == "__main__":
    img = Image.new("RGB", (400, 300), color="white")
    draw = ImageDraw.Draw(img)
    text_lines = ["METFORMIN 500MG", "Batch: B202", "MFG: 01/2024", "EXP: 12/2026"]
    y = 50
    for line in text_lines:
        draw.text((30, y), line, fill="black")
        y += 40

    img_path = Path("test_medicine.jpg")
    img.save(img_path)

    try:
        status, _ = _post_json("/auth/login", {"email": "demo@example.com", "password": "SecurePass123"})
        print(f"Auth smoke status: {status}")
    except urllib.error.HTTPError as exc:
        print(f"Auth smoke status: {exc.code}")

    with img_path.open("rb") as handle:
        status, body = _post_multipart("/scan", [("images", img_path.name, "image/jpeg", handle.read())])

    print("API /scan SUCCESS" if status == 200 else f"API /scan FAILED: {status}")
    print(body)

    try:
        img_path.unlink()
    except Exception:
        pass
