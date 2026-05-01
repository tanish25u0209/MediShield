#!/usr/bin/env python
"""
Run a sample MediShield scan against a live backend using images from samples/.

Usage:
  set GEMINI_API_KEY=your_key
  python run_sample_gemini.py --folder samples/samples/001 --limit 2

This script does not call Gemini directly. It sets up a real sample upload so the
backend can use Gemini fallback if its own logic decides to do so.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import requests


DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
DEFAULT_SAMPLE_FOLDER = Path(__file__).parent / "samples" / "samples" / "001"


def _collect_images(folder: Path, limit: int) -> list[Path]:
    if not folder.exists():
        raise FileNotFoundError(f"Sample folder not found: {folder}")

    candidates = sorted(
        [path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}],
        key=lambda path: path.name.lower(),
    )
    return candidates[:limit]


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload sample medicine images to the MediShield backend.")
    parser.add_argument("--backend", default=DEFAULT_BACKEND_URL, help="Backend base URL")
    parser.add_argument("--folder", default=str(DEFAULT_SAMPLE_FOLDER), help="Sample folder to use")
    parser.add_argument("--limit", type=int, default=2, help="Max number of images to upload")
    parser.add_argument("--medicine-name", default="", help="Optional medicine name to submit with the scan")
    args = parser.parse_args()

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("GEMINI_API_KEY is not set. Set it in your environment first.")
        return 1

    folder = Path(args.folder)
    images = _collect_images(folder, max(1, args.limit))
    if not images:
        print(f"No images found in {folder}")
        return 1

    print(f"Using GEMINI_API_KEY: yes")
    print(f"Backend: {args.backend}")
    print(f"Sample folder: {folder}")
    print("Images:")
    for image in images:
        print(f"  - {image.name}")

    files = []
    handles = []
    try:
        for image in images:
            handle = image.open("rb")
            handles.append(handle)
            mime = "image/jpeg" if image.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
            files.append(("images", (image.name, handle, mime)))

        data = {}
        if args.medicine_name.strip():
            data["medicine_name"] = args.medicine_name.strip()

        health = requests.get(f"{args.backend}/health", timeout=10)
        print(f"Health: {health.status_code}")
        health.raise_for_status()

        response = requests.post(f"{args.backend}/scan", data=data, files=files, timeout=180)
        print(f"Scan status: {response.status_code}")
        response.raise_for_status()

        payload = response.json()
        print("\nResult")
        print(f"Request ID: {payload.get('request_id')}")
        print(f"Status: {payload.get('status')}")
        print(f"Risk: {payload.get('risk_score')}")
        print(f"Confidence: {payload.get('confidence')}")
        parsed = payload.get("parsed_data") or {}
        print(f"Medicine: {parsed.get('medicine_name')}")
        print(f"Batch: {parsed.get('batch_number')}")

        drug = payload.get("drug_info") or {}
        if drug:
            print(f"Drug info: {drug.get('name')} | banned={drug.get('is_banned')} | fake={drug.get('is_fake_medicine')}")

        display_fields = payload.get("display_fields") or {}
        if display_fields:
            print("\nDisplay fields")
            for key, value in display_fields.items():
                if value:
                    print(f"  {key}: {value}")

        return 0
    finally:
        for handle in handles:
            try:
                handle.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
