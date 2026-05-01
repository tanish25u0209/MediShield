"""
Simple test to debug /scan endpoint
"""

import requests
from pathlib import Path

BACKEND_URL = "http://localhost:8000"
SAMPLES_DIR = Path(__file__).parent / "samples" / "samples"

# Test health first
try:
    resp = requests.get(f"{BACKEND_URL}/health", timeout=5)
    print(f"Health check: {resp.status_code}")
    print(f"Response: {resp.json()}")
except Exception as e:
    print(f"Health check failed: {e}")
    exit(1)

# Test /scan with one image
sample_path = SAMPLES_DIR / "001"
image_path = list(sample_path.glob("*.jpg"))[0]

print(f"\nTesting /scan with: {image_path}")
print(f"File size: {image_path.stat().st_size} bytes")

files = [("images", (image_path.name, open(image_path, "rb"), "image/jpeg"))]

try:
    resp = requests.post(f"{BACKEND_URL}/scan", files=files, timeout=30)
    print(f"Status: {resp.status_code}")
    print(f"Response body: {resp.text[:500]}")
except Exception as e:
    print(f"Error: {e}")
finally:
    files[0][1][1].close()
