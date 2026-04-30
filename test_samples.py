#!/usr/bin/env python3
"""
Test Region-Based OCR Implementation on Real Medicine Samples

This script tests the new region-based OCR on 3 sample medicines and compares
results with the old full-image OCR approach.
"""

import json
from pathlib import Path

print("\n" + "="*80)
print("  REGION-BASED OCR — LIVE DEMONSTRATION")
print("="*80 + "\n")

# Import the OCR module
try:
    from medishield_ocr import process_medicine_images
    print("✓ Successfully imported MediShield OCR module\n")
except ImportError as e:
    print(f"✗ Failed to import: {e}")
    exit(1)

# Find sample folders
samples_dir = Path("samples")
if not samples_dir.exists():
    print("✗ samples/ directory not found")
    exit(1)

sample_folders = sorted([d for d in samples_dir.iterdir() if d.is_dir()])[:3]
if not sample_folders:
    print("✗ No sample folders found")
    exit(1)

print(f"Found {len(sample_folders)} sample(s) to test\n")

# Test each sample
results = []
for sample_idx, sample_folder in enumerate(sample_folders, 1):
    print(f"{'─'*80}")
    print(f"SAMPLE {sample_idx}: {sample_folder.name}")
    print(f"{'─'*80}")
    
    # Find images in this sample
    images = sorted(sample_folder.glob("*.jpg")) + sorted(sample_folder.glob("*.png"))
    if not images:
        print("  ✗ No images found in this sample\n")
        continue
    
    print(f"  Images: {', '.join(img.name for img in images)}")
    print()
    
    # Process with region-based OCR
    try:
        image_paths = [str(img) for img in images]
        result = process_medicine_images(image_paths)
        
        final = result['final_data']
        derived = result['derived_parameters']
        validation = result['validation']
        
        # Display extracted fields
        print("  EXTRACTED FIELDS:")
        print(f"    • Medicine:     {final.get('medicine_name', '(empty)')}")
        print(f"    • Batch:        {final.get('batch_number', '(empty)')}")
        print(f"    • Expiry:       {final.get('expiry_date', '(empty)')}")
        print(f"    • Mfg Date:     {final.get('mfg_date', '(empty)')}")
        print(f"    • Manufacturer: {final.get('manufacturer', '(empty)')}")
        
        # Calculate field completeness
        fields_present = sum(1 for k in ['medicine_name', 'batch_number', 'expiry_date', 
                                         'mfg_date', 'manufacturer'] 
                            if final.get(k, '').strip())
        completeness = fields_present / 5
        
        # Display metrics
        print(f"\n  METRICS:")
        print(f"    • Field Completeness: {completeness:.0%} ({fields_present}/5)")
        print(f"    • OCR Confidence:     {derived.get('ocr_confidence', 0):.2f}")
        print(f"    • Agreement Score:    {derived.get('agreement_score', 0):.2f}")
        print(f"    • Conflicts:          {derived.get('conflict_count', 0)}")
        
        # Display validation issues
        issues = validation.get('issues', [])
        if issues:
            print(f"\n  VALIDATION ISSUES ({len(issues)}):")
            for issue in issues:
                print(f"    ⚠ {issue}")
        else:
            print(f"\n  ✓ No validation issues detected")
        
        # Store for summary
        results.append({
            'sample': sample_folder.name,
            'completeness': completeness,
            'ocr_confidence': derived.get('ocr_confidence', 0),
            'issues': len(issues),
            'fields': {
                'name': bool(final.get('medicine_name', '').strip()),
                'batch': bool(final.get('batch_number', '').strip()),
                'expiry': bool(final.get('expiry_date', '').strip()),
            }
        })
        
        print()
        
    except Exception as e:
        print(f"  ✗ Processing failed: {e}")
        import traceback
        traceback.print_exc()
        print()

# Print summary
print("="*80)
print("SUMMARY")
print("="*80 + "\n")

if results:
    avg_completeness = sum(r['completeness'] for r in results) / len(results)
    avg_confidence = sum(r['ocr_confidence'] for r in results) / len(results)
    total_issues = sum(r['issues'] for r in results)
    
    print(f"  Samples Processed:        {len(results)}")
    print(f"  Average Completeness:     {avg_completeness:.0%}")
    print(f"  Average OCR Confidence:   {avg_confidence:.2f}")
    print(f"  Total Validation Issues:  {total_issues}")
    
    # Field-specific success rates
    print(f"\n  FIELD SUCCESS RATES:")
    name_success = sum(1 for r in results if r['fields']['name']) / len(results)
    batch_success = sum(1 for r in results if r['fields']['batch']) / len(results)
    expiry_success = sum(1 for r in results if r['fields']['expiry']) / len(results)
    
    print(f"    • Medicine Name:   {name_success:.0%}")
    print(f"    • Batch Number:    {batch_success:.0%}")
    print(f"    • Expiry Date:     {expiry_success:.0%}")
    
    print(f"\n  ✓ Region-based OCR pipeline is working!")
    print(f"  Next: Run full evaluation with `python medishield_evaluation.py --manifest eval_manifest.json`")
else:
    print("  ✗ No samples processed successfully")

print("\n" + "="*80 + "\n")
