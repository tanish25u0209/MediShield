"""
Inline test of region-based OCR.
"""
import json
import sys
from pathlib import Path

# Test if medishield_ocr can be imported
try:
    from medishield_ocr import process_medicine_images
    print("✓ Successfully imported medishield_ocr module")
except Exception as e:
    print(f"✗ Failed to import: {e}")
    sys.exit(1)

# Find test images
test_dir = Path("medishield_data/test")
if test_dir.exists():
    images = sorted(test_dir.glob("*.jpg"))[:1]
    if images:
        print(f"\n▶ Testing region-based OCR on: {images[0].name}\n")
        try:
            result = process_medicine_images([str(images[0])])
            final = result['final_data']
            
            print("EXTRACTED FIELDS:")
            print(f"  Medicine:    {final.get('medicine_name', '(empty)')}")
            print(f"  Batch:       {final.get('batch_number', '(empty)')}")
            print(f"  Expiry:      {final.get('expiry_date', '(empty)')}")
            print(f"  Mfg Date:    {final.get('mfg_date', '(empty)')}")
            print(f"  Manufacturer:{final.get('manufacturer', '(empty)')}")
            
            print(f"\nMETRICS:")
            derived = result['derived_parameters']
            print(f"  OCR Confidence: {derived.get('ocr_confidence', 0)}")
            print(f"  Conflicts: {derived.get('conflict_count', 0)}")
            print(f"  Issues: {derived.get('issue_count', 0)}")
            
            issues = result['validation'].get('issues', [])
            if issues:
                print(f"\n  Validation issues:")
                for issue in issues:
                    print(f"    - {issue}")
            
            print("\n✓ Region-based OCR completed successfully!")
        except Exception as e:
            print(f"✗ Test failed: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("No test images found in medishield_data/test/")
else:
    print(f"Test directory not found: {test_dir}")
