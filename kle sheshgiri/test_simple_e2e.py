"""
End-to-end test with mock OCR - tests API, database, and response generation
without depending on complex OCR/barcode modules
"""

import json
import requests
from pathlib import Path

BACKEND_URL = "http://localhost:8000"

# Test 1: Health check
print("\n" + "="*80)
print("TEST 1: Health Check")
print("="*80)
try:
    resp = requests.get(f"{BACKEND_URL}/health", timeout=5)
    print(f"Status: {resp.status_code}")
    data = resp.json()
    print(f"Response: {json.dumps(data, indent=2)}")
    print("✅ PASS" if resp.status_code == 200 else "❌ FAIL")
except Exception as e:
    print(f"❌ FAIL: {e}")

# Test 2: Upload single image
print("\n" + "="*80)
print("TEST 2: Upload Single Sample Image")
print("="*80)

sample_path = Path(__file__).parent / "samples" / "samples" / "001"
image_path = list(sample_path.glob("*.jpg"))[0]

print(f"Image: {image_path.name} ({image_path.stat().st_size} bytes)")

files = [("images", (image_path.name, open(image_path, "rb"), "image/jpeg"))]

try:
    resp = requests.post(f"{BACKEND_URL}/scan", files=files, timeout=60)
    files[0][1][1].close()
    
    print(f"Status: {resp.status_code}")
    
    if resp.status_code == 200:
        data = resp.json()
        print(f"\n✅ PASS - Scan successful")
        print(f"\nRequest ID: {data.get('request_id')}")
        print(f"Status: {data.get('status')}")
        print(f"Risk Score: {data.get('risk_score')}")
        print(f"Confidence: {data.get('confidence')}")
        print(f"\nParsed Fields:")
        if data.get('parsed_data'):
            for key, value in data['parsed_data'].items():
                if value:
                    print(f"  • {key}: {value}")
        print(f"\nIssues Found: {len(data.get('reasons', []))}")
        for issue in data.get('reasons', [])[:3]:
            print(f"  • {issue.get('code')}: {issue.get('message')}")
    else:
        print(f"❌ FAIL - Status {resp.status_code}")
        print(f"Response: {resp.text[:200]}")
        
except Exception as e:
    print(f"❌ FAIL: {e}")
    files[0][1][1].close()

# Test 3: Multiple images
print("\n" + "="*80)
print("TEST 3: Upload Multiple Sample Images")
print("="*80)

sample_path = Path(__file__).parent / "samples" / "samples" / "002"
image_paths = sorted(list(sample_path.glob("*.jpg")))[:3]

print(f"Uploading {len(image_paths)} images...")

files = [(("images", (img.name, open(img, "rb"), "image/jpeg"))) for img in image_paths]

try:
    resp = requests.post(f"{BACKEND_URL}/scan", files=files, timeout=60)
    for _, file_tuple in files:
        file_tuple[1].close()
    
    print(f"Status: {resp.status_code}")
    
    if resp.status_code == 200:
        data = resp.json()
        print(f"✅ PASS - Multi-image scan successful")
        print(f"\nRequest ID: {data.get('request_id')}")
        print(f"Status: {data.get('status')}")
        print(f"Risk Score: {data.get('risk_score')}")
        print(f"Diagnostics: {len(data.get('diagnostics', []))} images analyzed")
    else:
        print(f"❌ FAIL - Status {resp.status_code}")
        print(f"Response: {resp.text[:200]}")
        
except Exception as e:
    print(f"❌ FAIL: {e}")
    for _, file_tuple in files:
        file_tuple[1].close()

print("\n" + "="*80)
print("TESTS COMPLETED")
print("="*80)
