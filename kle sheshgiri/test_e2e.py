"""
End-to-End MediShield Test: Simulate user uploading sample images through frontend
Tests the complete OCR → Validation → Risk Scoring → Response pipeline
"""

import json
import sys
import time
from pathlib import Path
import requests

# Force UTF-8 encoding on Windows
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Backend URL
BACKEND_URL = "http://localhost:8000"
SCAN_ENDPOINT = f"{BACKEND_URL}/scan"

# Sample images path
SAMPLES_DIR = Path(__file__).parent / "samples" / "samples"

def print_header(title: str):
    """Print formatted section header"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)

def print_section(title: str):
    """Print formatted subsection"""
    print(f"\n{'─' * 80}")
    print(f"  {title}")
    print(f"{'─' * 80}")

def upload_sample(sample_number: int):
    """Upload a sample folder's images to the backend"""
    sample_path = SAMPLES_DIR / f"00{sample_number}" if sample_number < 10 else SAMPLES_DIR / f"0{sample_number}"
    
    if not sample_path.exists():
        print(f"❌ Sample {sample_number:03d} not found at {sample_path}")
        return None
    
    # Get all images in sample folder
    image_files = sorted([f for f in sample_path.glob("*") if f.suffix.lower() in [".jpg", ".png", ".jpeg"]])
    
    if not image_files:
        print(f"❌ No images found in {sample_path}")
        return None
    
    print(f"\n📁 Found {len(image_files)} image(s) in sample 00{sample_number}:")
    for img in image_files:
        print(f"   • {img.name}")
    
    # Prepare multipart file upload
    files = []
    for img_path in image_files:
        files.append(("images", (img_path.name, open(img_path, "rb"), "image/jpeg")))
    
    print(f"\n🔄 Uploading {len(files)} image(s) to {SCAN_ENDPOINT}...")
    
    try:
        response = requests.post(SCAN_ENDPOINT, files=files, timeout=60)
        
        # Close all opened files
        for _, file_tuple in files:
            file_tuple[1].close()
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Upload successful!")
            return result
        else:
            print(f"❌ Upload failed with status {response.status_code}")
            print(f"Response: {response.text}")
            return None
    
    except requests.exceptions.ConnectionError:
        print(f"❌ Cannot connect to backend at {BACKEND_URL}")
        print("   Make sure the backend is running: python -m uvicorn main:app ...")
        return None
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return None

def display_parsed_data(parsed_data: dict):
    """Display extracted medicine data"""
    print_section("📦 EXTRACTED MEDICINE DATA")
    
    fields = [
        ("Medicine Name", "medicine_name"),
        ("Brand Name", "brand_name"),
        ("Dosage Strength", "dosage_strength"),
        ("Dosage Form", "dosage_form"),
        ("Batch Number", "batch_number"),
        ("Manufacturing Date", "manufacturing_date"),
        ("Expiry Date", "expiry_date"),
        ("Manufacturer", "manufacturer_name"),
        ("MRP Price", "mrp_price"),
        ("Composition", "composition"),
        ("License Number", "license_number"),
        ("Barcode Number", "barcode_number"),
    ]
    
    for label, key in fields:
        value = parsed_data.get(key, "N/A")
        status = "✓" if value and value != "N/A" else "✗"
        print(f"  {status} {label:20s}: {value}")

def display_diagnostics(diagnostics: list):
    """Display image quality diagnostics"""
    print_section("🔍 IMAGE QUALITY DIAGNOSTICS")
    
    for diag in diagnostics:
        idx = diag.get("image_index", "?")
        blurry = "🔴 BLURRY" if diag.get("is_blurry") else "✅"
        low_quality = "🔴 LOW QUALITY" if diag.get("is_low_quality") else "✅"
        distorted = "🔴 DISTORTED" if diag.get("is_distorted") else "✅"
        
        print(f"\n  Image {idx}:")
        print(f"    • Blur Status:       {blurry}")
        print(f"    • Quality Status:    {low_quality}")
        print(f"    • Distortion Status: {distorted}")

def display_risk_assessment(result: dict):
    """Display risk score and confidence"""
    print_section("⚠️ RISK ASSESSMENT")
    
    status = result.get("status", "Unknown")
    risk_score = result.get("risk_score", 0)
    confidence = result.get("confidence", 0)
    
    # Status indicator
    if status == "High Risk":
        status_emoji = "🔴"
    elif status == "Suspicious":
        status_emoji = "🟡"
    else:
        status_emoji = "🟢"
    
    print(f"\n  Status:        {status_emoji} {status}")
    print(f"  Risk Score:    {risk_score}/100")
    print(f"  Confidence:    {confidence:.1f}%")
    
    # Risk bar
    filled = int(risk_score / 5)
    empty = 20 - filled
    bar = "█" * filled + "░" * empty
    print(f"  Risk Bar:      [{bar}]")

def display_issues(reasons: list):
    """Display validation and consistency issues"""
    if not reasons:
        print("\n  ✅ No issues detected!")
        return
    
    print_section("❌ DETECTED ISSUES")
    
    for issue in reasons:
        code = issue.get("code", "unknown")
        message = issue.get("message", "No message")
        severity = issue.get("severity", "medium")
        
        # Severity emoji
        if severity == "high":
            sev_emoji = "🔴"
        elif severity == "medium":
            sev_emoji = "🟡"
        else:
            sev_emoji = "⚪"
        
        print(f"\n  {sev_emoji} [{code.upper()}]")
        print(f"     {message}")

def display_drug_info(drug_info):
    """Display drug reference information"""
    if not drug_info:
        return
    
    print_section("💊 DRUG REFERENCE CHECK")
    
    name = drug_info.get("name", "Unknown")
    is_banned = drug_info.get("is_banned", False)
    is_fake = drug_info.get("is_fake_medicine", False)
    is_true = drug_info.get("is_true_medicine", False)
    
    print(f"\n  Drug Name: {name}")
    print(f"  • Banned:            {'🔴 YES' if is_banned else '✅ NO'}")
    print(f"  • Known Fake:        {'🔴 YES' if is_fake else '✅ NO'}")
    print(f"  • Verified True:     {'🟢 YES' if is_true else '⚪ NO'}")

def display_gemini_fallback(gemini_info):
    """Display Gemini fallback information if used"""
    if not gemini_info or not gemini_info.get("triggered"):
        return
    
    print_section("🤖 GOOGLE GEMINI FALLBACK (Enhanced Extraction)")
    
    print(f"\n  Status: ✅ TRIGGERED")
    print(f"  Reason: {gemini_info.get('reason', 'N/A')}")
    
    # Show Gemini-enhanced fields
    if gemini_info.get("gemini_extracted_fields"):
        print(f"\n  Gemini-Enhanced Fields:")
        for key, value in gemini_info.get("gemini_extracted_fields", {}).items():
            if value:
                print(f"    • {key}: {value}")
    
    # Show conflict resolutions
    if gemini_info.get("conflict_resolution"):
        print(f"\n  Conflict Resolutions:")
        for field, resolution in gemini_info.get("conflict_resolution", {}).items():
            final = resolution.get("final_value", "N/A")
            confidence = resolution.get("confidence", 0)
            reason = resolution.get("reason", "")
            print(f"    • {field}:")
            print(f"        Final Value: {final}")
            print(f"        Confidence: {confidence}%")
            print(f"        Reason: {reason}")
    
    # Show summary
    if gemini_info.get("summary"):
        print(f"\n  User Summary:")
        print(f"  {gemini_info.get('summary')}")

def display_full_result(result: dict):
    """Display complete scan result"""
    print_header("🏥 MEDISHIELD SCAN RESULT")
    
    # Request ID
    request_id = result.get("request_id", "unknown")
    print(f"\nRequest ID: {request_id}")
    
    # Parsed data
    if result.get("parsed_data"):
        display_parsed_data(result["parsed_data"])
    
    # Diagnostics
    if result.get("diagnostics"):
        display_diagnostics(result["diagnostics"])
    
    # Risk assessment
    display_risk_assessment(result)
    
    # Issues
    if result.get("reasons"):
        display_issues(result["reasons"])
    
    # Drug info
    if result.get("drug_info"):
        display_drug_info(result["drug_info"])
    
    # Gemini fallback (if used)
    if result.get("gemini_fallback"):
        display_gemini_fallback(result["gemini_fallback"])
    
    print("\n" + "=" * 80)

def main():
    """Run end-to-end test"""
    print_header("🧪 MEDISHIELD END-TO-END TEST")
    print("""
This test simulates a real user uploading sample medicine package images
through the MediShield frontend to the backend API.

The pipeline includes:
  1. Image preprocessing & quality check
  2. OCR text extraction
  3. Barcode/QR code scanning
  4. Field parsing & normalization
  5. Batch tracking & anomaly detection
  6. Risk scoring & confidence calculation
  7. Drug reference lookup
  8. Response generation
  (+ optional Gemini fallback if confidence is low)
    """)
    
    # Test samples
    test_samples = [1, 2, 3]
    
    results = []
    for sample_num in test_samples:
        print_header(f"SAMPLE {sample_num:03d} TEST")
        result = upload_sample(sample_num)
        if result:
            results.append(result)
            display_full_result(result)
            time.sleep(1)  # Small delay between requests
        else:
            print(f"⏭️  Skipping sample {sample_num:03d}...")
            time.sleep(1)
    
    # Summary
    if results:
        print_header("📊 TEST SUMMARY")
        print(f"\n✅ Successfully scanned: {len(results)} sample(s)")
        
        for i, result in enumerate(results, 1):
            status = result.get("status", "Unknown")
            risk = result.get("risk_score", 0)
            confidence = result.get("confidence", 0)
            print(f"\n  Sample {i}:")
            print(f"    Status: {status}")
            print(f"    Risk Score: {risk}/100")
            print(f"    Confidence: {confidence:.1f}%")
    else:
        print("\n❌ No samples were successfully scanned. Check backend connectivity.")

if __name__ == "__main__":
    main()
