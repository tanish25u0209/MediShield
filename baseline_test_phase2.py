#!/usr/bin/env python3
"""
BASELINE TEST - PHASE 2: Old OCR vs New Region-Based OCR

NOW WITH PROPER RESOLUTION IMAGES (800×800px)

This script compares both approaches on the new proper-quality dataset
to measure real improvement.

Usage:
    python baseline_test_phase2.py [--data-dir medishield_data]
"""

import json
import sys
import os
from pathlib import Path
from dataclasses import dataclass
import argparse

# Fix Windows console encoding
if sys.platform == 'win32':
    os.system('chcp 65001 > nul')
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

print("\n" + "="*90)
print("  PHASE 2: BASELINE ESTABLISHMENT")
print("  Comparing Old OCR vs New Region-Based OCR on Proper-Quality Images")
print("="*90 + "\n")

# Import OCR module
try:
    from medishield_ocr import (
        process_medicine_images, extract_text, extract_fields,
        preprocess_image, _load_image_bgr, MedicineFields
    )
    print("[OK] OCR module imported\n")
except ImportError as e:
    print(f"[ERROR] Import failed: {e}")
    sys.exit(1)

@dataclass
class Comparison:
    sample_name: str
    images_count: int
    old_batch: bool
    old_expiry: bool
    old_mfg: bool
    old_name: bool
    old_maker: bool
    old_complete: int
    new_batch: bool
    new_expiry: bool
    new_mfg: bool
    new_name: bool
    new_maker: bool
    new_complete: int

def evaluate_fields(final_data: dict) -> tuple[bool, bool, bool, bool, bool, int]:
    """Extract key metrics for comparison."""
    batch = bool(final_data.get('batch_number', '').strip())
    expiry = bool(final_data.get('expiry_date', '').strip())
    mfg = bool(final_data.get('mfg_date', '').strip())
    name = bool(final_data.get('medicine_name', '').strip())
    maker = bool(final_data.get('manufacturer', '').strip())
    complete = sum([name, batch, expiry, mfg, maker])
    return batch, expiry, mfg, name, maker, complete

def run_old_ocr(image_paths: list) -> dict:
    """
    OLD OCR: Full-image extraction without region detection.
    Uses extract_fields() directly on combined OCR text.
    """
    all_raw_text = []
    for img_path in image_paths:
        try:
            preprocessed = preprocess_image(img_path)
            raw_text = extract_text(preprocessed)
            all_raw_text.append(raw_text)
        except Exception as e:
            pass
    
    combined_text = "\n".join(all_raw_text)
    try:
        fields = extract_fields(combined_text)
        return {
            'final_data': {
                'medicine_name': fields.medicine_name,
                'batch_number': fields.batch_number,
                'expiry_date': fields.expiry_date,
                'mfg_date': fields.mfg_date,
                'manufacturer': fields.manufacturer,
            }
        }
    except:
        return {'final_data': {
            'medicine_name': '',
            'batch_number': '',
            'expiry_date': '',
            'mfg_date': '',
            'manufacturer': '',
        }}

def run_new_ocr(image_paths: list) -> dict:
    """
    NEW OCR: Region-based extraction (default in process_medicine_images).
    """
    try:
        return process_medicine_images(image_paths)
    except:
        return {'final_data': {
            'medicine_name': '',
            'batch_number': '',
            'expiry_date': '',
            'mfg_date': '',
            'manufacturer': '',
        }}

def main():
    parser = argparse.ArgumentParser(description="Phase 2: Baseline Establishment")
    parser.add_argument("--data-dir", default="medishield_data", help="Dataset directory")
    parser.add_argument("--max-samples", type=int, default=15, help="Max samples to test")
    args = parser.parse_args()
    
    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"[ERROR] Dataset directory not found: {data_dir}")
        sys.exit(1)
    
    # Load metadata for ground truth
    metadata_file = data_dir / "metadata.json"
    ground_truth = {}
    if metadata_file.exists():
        try:
            ground_truth = json.loads(metadata_file.read_text())
            print(f"[OK] Loaded ground truth from metadata\n")
        except:
            print("⚠ Could not load ground truth metadata\n")
    
    # Find sample folders
    sample_folders = sorted([d for d in (data_dir / "raw").iterdir() if d.is_dir()])[:args.max_samples]
    
    if not sample_folders:
        print(f"[ERROR] No samples found in {data_dir}/raw/")
        sys.exit(1)
    
    print(f"Testing {len(sample_folders)} samples\n")
    print("-" * 130)
    print(f"{'Sample':25} | {'Imgs':>3} | {'OLD OCR':^55} | {'NEW OCR':^55} | {'Status':^8}")
    print(f"{'':25} | {'':>3} | {'B  E  M  N  K  /5':^55} | {'B  E  M  N  K  /5':^55} | {'':^8}")
    print("-" * 130)
    
    comparisons = []
    improvements = {'batch': 0, 'expiry': 0, 'mfg': 0, 'name': 0, 'maker': 0, 'overall': 0}
    
    for sample_idx, sample_folder in enumerate(sample_folders, 1):
        images = sorted(sample_folder.glob("*.jpg")) + sorted(sample_folder.glob("*.png"))
        if not images:
            continue
        
        image_paths = [str(img) for img in images]
        sample_key = sample_folder.name
        
        try:
            # Run OLD OCR
            result_old = run_old_ocr(image_paths)
            old_batch, old_expiry, old_mfg, old_name, old_maker, old_complete = evaluate_fields(result_old['final_data'])
            
            # Run NEW OCR
            result_new = run_new_ocr(image_paths)
            new_batch, new_expiry, new_mfg, new_name, new_maker, new_complete = evaluate_fields(result_new['final_data'])
            
            # Track improvements
            if new_batch and not old_batch: improvements['batch'] += 1
            if new_expiry and not old_expiry: improvements['expiry'] += 1
            if new_mfg and not old_mfg: improvements['mfg'] += 1
            if new_name and not old_name: improvements['name'] += 1
            if new_maker and not old_maker: improvements['maker'] += 1
            if new_complete > old_complete: improvements['overall'] += 1
            
            # Format output
            old_str = f"{'Y' if old_batch else 'N'}  {'Y' if old_expiry else 'N'}  {'Y' if old_mfg else 'N'}  {'Y' if old_name else 'N'}  {'Y' if old_maker else 'N'}  {old_complete}"
            new_str = f"{'Y' if new_batch else 'N'}  {'Y' if new_expiry else 'N'}  {'Y' if new_mfg else 'N'}  {'Y' if new_name else 'N'}  {'Y' if new_maker else 'N'}  {new_complete}"
            
            # Status indicator
            if new_complete > old_complete:
                status = "+ GAIN"
            elif new_complete < old_complete:
                status = "- LOSS"
            else:
                status = "= SAME"
            
            print(f"{sample_key[:25]:25} | {len(images):3d} | {old_str:^55} | {new_str:^55} | {status:^8}")
            
            comparisons.append(Comparison(
                sample_name=sample_key,
                images_count=len(images),
                old_batch=old_batch, old_expiry=old_expiry, old_mfg=old_mfg, old_name=old_name, old_maker=old_maker, old_complete=old_complete,
                new_batch=new_batch, new_expiry=new_expiry, new_mfg=new_mfg, new_name=new_name, new_maker=new_maker, new_complete=new_complete
            ))
            
        except Exception as e:
            print(f"{sample_key[:25]:25} | {len(images):3d} | [ERROR] {str(e)[:43]:43} |")
    
    print("-" * 130)
    
    # Summary
    print("\n" + "="*90)
    print("BASELINE ESTABLISHMENT SUMMARY")
    print("="*90 + "\n")
    
    if comparisons:
        total = len(comparisons)
        
        # OLD OCR metrics
        old_batch_rate = sum(1 for c in comparisons if c.old_batch) / total
        old_expiry_rate = sum(1 for c in comparisons if c.old_expiry) / total
        old_mfg_rate = sum(1 for c in comparisons if c.old_mfg) / total
        old_name_rate = sum(1 for c in comparisons if c.old_name) / total
        old_maker_rate = sum(1 for c in comparisons if c.old_maker) / total
        old_avg_complete = sum(c.old_complete for c in comparisons) / total
        
        # NEW OCR metrics
        new_batch_rate = sum(1 for c in comparisons if c.new_batch) / total
        new_expiry_rate = sum(1 for c in comparisons if c.new_expiry) / total
        new_mfg_rate = sum(1 for c in comparisons if c.new_mfg) / total
        new_name_rate = sum(1 for c in comparisons if c.new_name) / total
        new_maker_rate = sum(1 for c in comparisons if c.new_maker) / total
        new_avg_complete = sum(c.new_complete for c in comparisons) / total
        
        # Gains
        batch_gain = new_batch_rate - old_batch_rate
        expiry_gain = new_expiry_rate - old_expiry_rate
        mfg_gain = new_mfg_rate - old_mfg_rate
        name_gain = new_name_rate - old_name_rate
        maker_gain = new_maker_rate - old_maker_rate
        complete_gain = new_avg_complete - old_avg_complete
        
        print("OLD OCR (Full-Image):")
        print(f"  Batch:       {old_batch_rate:6.0%}  |  Expiry:     {old_expiry_rate:6.0%}")
        print(f"  Mfg:         {old_mfg_rate:6.0%}  |  Name:       {old_name_rate:6.0%}")
        print(f"  Maker:       {old_maker_rate:6.0%}  |  Avg Score:  {old_avg_complete:.2f}/5")
        
        print(f"\nNEW OCR (Region-Based):")
        print(f"  Batch:       {new_batch_rate:6.0%}  |  Expiry:     {new_expiry_rate:6.0%}")
        print(f"  Mfg:         {new_mfg_rate:6.0%}  |  Name:       {new_name_rate:6.0%}")
        print(f"  Maker:       {new_maker_rate:6.0%}  |  Avg Score:  {new_avg_complete:.2f}/5")
        
        print(f"\nIMPROVEMENT (OLD → NEW):")
        print(f"  Batch:       {old_batch_rate:6.0%} → {new_batch_rate:6.0%}  ({batch_gain:+6.0%})")
        print(f"  Expiry:      {old_expiry_rate:6.0%} → {new_expiry_rate:6.0%}  ({expiry_gain:+6.0%})")
        print(f"  Mfg:         {old_mfg_rate:6.0%} → {new_mfg_rate:6.0%}  ({mfg_gain:+6.0%})")
        print(f"  Name:        {old_name_rate:6.0%} → {new_name_rate:6.0%}  ({name_gain:+6.0%})")
        print(f"  Maker:       {old_maker_rate:6.0%} → {new_maker_rate:6.0%}  ({maker_gain:+6.0%})")
        print(f"  Avg Score:   {old_avg_complete:6.2f} → {new_avg_complete:6.2f}  ({complete_gain:+6.2f})")
        
        print(f"\nSAMPLES WITH IMPROVEMENTS:")
        print(f"  Batch improved:      {improvements['batch']:2d}/{total}")
        print(f"  Expiry improved:     {improvements['expiry']:2d}/{total}")
        print(f"  Mfg improved:        {improvements['mfg']:2d}/{total}")
        print(f"  Name improved:       {improvements['name']:2d}/{total}")
        print(f"  Maker improved:      {improvements['maker']:2d}/{total}")
        print(f"  Overall improved:    {improvements['overall']:2d}/{total}")
        
        # Save report
        report = {
            'phase': 2,
            'status': 'complete',
            'total_samples': total,
            'dataset': str(data_dir),
            'old_ocr': {
                'batch_rate': old_batch_rate,
                'expiry_rate': old_expiry_rate,
                'mfg_rate': old_mfg_rate,
                'name_rate': old_name_rate,
                'maker_rate': old_maker_rate,
                'avg_completeness': old_avg_complete,
            },
            'new_ocr': {
                'batch_rate': new_batch_rate,
                'expiry_rate': new_expiry_rate,
                'mfg_rate': new_mfg_rate,
                'name_rate': new_name_rate,
                'maker_rate': new_maker_rate,
                'avg_completeness': new_avg_complete,
            },
            'improvements': {
                'batch': batch_gain,
                'expiry': expiry_gain,
                'mfg': mfg_gain,
                'name': name_gain,
                'maker': maker_gain,
                'overall': complete_gain,
                'samples_batch_improved': improvements['batch'],
                'samples_expiry_improved': improvements['expiry'],
                'samples_overall_improved': improvements['overall'],
            }
        }
        
        report_path = Path("baseline_phase2_results.json")
        report_path.write_text(json.dumps(report, indent=2))
        print(f"\n[OK] Report saved to {report_path}")
        
        # Decision logic
        print(f"\n" + "="*90)
        print("PHASE 2 ANALYSIS & DECISION")
        print("="*90 + "\n")
        
        if complete_gain >= 0.5:
            print(f"[GOOD] REGION-BASED OCR SHOWS IMPROVEMENT ({complete_gain:+.2f} fields overall)")
            print("  Recommendation: Keep region-based architecture, move to Phase 3 optimization")
        elif complete_gain >= 0:
            print(f"[OK] SIMILAR PERFORMANCE (slight gain: {complete_gain:+.2f})")
            print("  Recommendation: Region-based is viable, consider simpler old approach OR optimize region detection")
        else:
            print(f"[BAD] REGION-BASED OCR UNDERPERFORMS ({complete_gain:+.2f} fields)")
            print("  Recommendation: Return to full-image extraction (simpler, faster, more reliable)")
            print("                  OR debug region detection logic")
        
        print("\n" + "="*90)
        print("NEXT STEPS:")
        print("="*90)
        print("1. Review individual sample failures (_analyze_failures.py coming next)")
        print("2. If improvement > 0.5: Proceed to Phase 3 (architecture refinement)")
        print("3. If improvement < 0: Consider simpler full-image approach")
        print("4. Update system README with findings")
    
    else:
        print("[ERROR] No valid samples processed")
        sys.exit(1)

if __name__ == "__main__":
    main()
