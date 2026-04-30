"""
Quick test of region-based OCR improvements.
"""
from pathlib import Path
from medishield_ocr import process_medicine_images

# Test with the same images (if they exist)
test_images_dir = Path("medishield_data") / "test"
if not test_images_dir.exists():
    print(f"Test images directory not found: {test_images_dir}")
    print("Skipping region-based OCR test.")
    exit(0)

images = sorted(test_images_dir.glob("*.jpg"))[:3]  # First 3 images
if not images:
    print("No test images found.")
    exit(0)

print(f"\n{'='*70}")
print("REGION-BASED OCR TEST")
print(f"{'='*70}")
print(f"\nTesting {len(images)} image(s) with region-based extraction...\n")

for img_path in images:
    print(f"\n[TEST] {img_path.name}")
    result = process_medicine_images([str(img_path)])
    
    final = result['final_data']
    print(f"  Medicine: {final.get('medicine_name', 'N/A')}")
    print(f"  Batch:    {final.get('batch_number', 'N/A')}")
    print(f"  Expiry:   {final.get('expiry_date', 'N/A')}")
    print(f"  Mfg:      {final.get('mfg_date', 'N/A')}")
    print(f"  Manuf:    {final.get('manufacturer', 'N/A')}")
    
    derived = result['derived_parameters']
    print(f"  OCR Confidence: {derived.get('ocr_confidence', 0.0)}")
    print(f"  Missing Fields: {derived.get('missing_field_ratio', 1.0):.1%}")
    
    issues = result['validation'].get('issues', [])
    if issues:
        print(f"  Validation issues: {len(issues)}")
        for issue in issues[:2]:
            print(f"    - {issue}")
    
print(f"\n{'='*70}")
print("Region-based OCR test complete.")
print(f"{'='*70}\n")
