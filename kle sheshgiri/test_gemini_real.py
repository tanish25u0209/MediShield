"""
Test Google Gemini fallback integration with real API key
Uploads sample medicine images and demonstrates Gemini enhancement
"""

import os
import json
import requests
from pathlib import Path

# Set the Gemini API key
API_KEY = "AIzaSyBIFpQCr_wTSC1TN6tYlwJsbQ_mu7uQJ-w"
os.environ["GEMINI_API_KEY"] = API_KEY

BACKEND_URL = "http://localhost:8000"
SAMPLES_DIR = Path(__file__).parent / "samples" / "samples"

def print_section(title: str):
    """Print section header"""
    print("\n" + "="*80)
    print(f"  {title}")
    print("="*80)

def test_gemini_fallback():
    """Test Gemini fallback with sample images"""
    
    print_section("MEDISHIELD GEMINI FALLBACK TEST")
    print(f"API Key Set: {bool(os.environ.get('GEMINI_API_KEY'))}")
    print(f"Backend URL: {BACKEND_URL}")
    
    # Test 1: Health check
    print_section("1. Health Check")
    try:
        resp = requests.get(f"{BACKEND_URL}/health", timeout=5)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            print("✅ Backend is running")
        else:
            print(f"⚠️  Unexpected status: {resp.status_code}")
    except Exception as e:
        print(f"❌ Backend not responding: {e}")
        return
    
    # Test 2: Upload images to trigger Gemini
    print_section("2. Upload Sample Images (May Trigger Gemini Fallback)")
    
    # Use sample 001 images
    sample_path = SAMPLES_DIR / "001"
    image_paths = sorted(list(sample_path.glob("*.jpg")))[:2]  # Use 2 images
    
    if not image_paths:
        print(f"❌ No sample images found in {sample_path}")
        return
    
    print(f"Uploading {len(image_paths)} images:")
    for img in image_paths:
        print(f"  • {img.name} ({img.stat().st_size} bytes)")
    
    # Prepare files
    files = []
    for img_path in image_paths:
        files.append(("images", (img_path.name, open(img_path, "rb"), "image/jpeg")))
    
    print(f"\nSending to {BACKEND_URL}/scan...")
    
    try:
        resp = requests.post(f"{BACKEND_URL}/scan", files=files, timeout=120)
        
        # Close files
        for _, file_tuple in files:
            file_tuple[1].close()
        
        print(f"Status: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            
            print_section("3. Scan Response")
            print(f"✅ Scan successful")
            print(f"\nRequest ID: {data.get('request_id')}")
            print(f"Status: {data.get('status')}")
            print(f"Risk Score: {data.get('risk_score')}/100")
            print(f"Confidence: {data.get('confidence'):.1f}%")
            
            # Display parsed data
            print_section("4. Extracted Medicine Data")
            parsed = data.get('parsed_data', {})
            for key, value in parsed.items():
                if value:
                    print(f"  • {key}: {value}")
            
            # Display issues
            if data.get('reasons'):
                print_section("5. Issues Detected")
                for issue in data.get('reasons', []):
                    print(f"  • [{issue.get('code')}] {issue.get('message')}")
            
            # Display Gemini fallback info
            gemini_info = data.get('gemini_fallback')
            if gemini_info and gemini_info.get('triggered'):
                print_section("6. Google Gemini Fallback (ENHANCED EXTRACTION)")
                print(f"✅ TRIGGERED")
                print(f"Reason: {gemini_info.get('reason')}")
                
                if gemini_info.get('gemini_extracted_fields'):
                    print(f"\nGemini-Enhanced Fields:")
                    for key, value in gemini_info.get('gemini_extracted_fields', {}).items():
                        if value:
                            print(f"  • {key}: {value}")
                
                if gemini_info.get('conflict_resolution'):
                    print(f"\nConflict Resolutions:")
                    for field, res in gemini_info.get('conflict_resolution', {}).items():
                        print(f"  • {field}:")
                        print(f"      Final: {res.get('final_value')}")
                        print(f"      Confidence: {res.get('confidence')}%")
                        print(f"      Reason: {res.get('reason')}")
                
                if gemini_info.get('summary'):
                    print(f"\nUser Summary:")
                    print(f"  {gemini_info.get('summary')}")
            else:
                print_section("6. No Gemini Fallback")
                print("Gemini was not needed (confidence was sufficient)")
            
            # Display drug info
            if data.get('drug_info'):
                print_section("7. Drug Reference Check")
                drug = data.get('drug_info', {})
                print(f"Name: {drug.get('name')}")
                print(f"Banned: {drug.get('is_banned')}")
                print(f"Known Fake: {drug.get('is_fake_medicine')}")
            
            print_section("TEST COMPLETE")
            print("✅ Full end-to-end Gemini test successful!")
            
        else:
            print(f"❌ Error: {resp.status_code}")
            print(f"Response: {resp.text[:300]}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        for _, file_tuple in files:
            file_tuple[1].close()

if __name__ == "__main__":
    test_gemini_fallback()
