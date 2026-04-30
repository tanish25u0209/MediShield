"""
Baseline Establishment: Old OCR vs New Region-Based OCR

This script demonstrates the actual improvement by running both approaches
on the same images and comparing field extraction rates.
"""

import json
from pathlib import Path
from dataclasses import dataclass

print("\n" + "="*90)
print("  BASELINE TEST: Old Full-Image OCR vs New Region-Based OCR")
print("="*90 + "\n")

try:
    from medishield_ocr import (
        process_medicine_images, extract_text, extract_fields,
        preprocess_image, _load_image_bgr, MedicineFields
    )
    print("✓ OCR module imported\n")
except ImportError as e:
    print(f"✗ Import failed: {e}")
    exit(1)

@dataclass
class OCRComparison:
    """Stores comparison of old vs new extraction."""
    sample_name: str
    old_batch: bool
    old_expiry: bool
    old_completeness: int
    new_batch: bool
    new_expiry: bool
    new_completeness: int
    batch_improvement: str
    expiry_improvement: str

def evaluate_fields(final_data: dict) -> tuple[bool, bool, int]:
    """Extract key metrics: batch, expiry, total completeness."""
    batch = bool(final_data.get('batch_number', '').strip())
    expiry = bool(final_data.get('expiry_date', '').strip())
    completeness = sum([
        bool(final_data.get('medicine_name', '').strip()),
        bool(final_data.get('batch_number', '').strip()),
        bool(final_data.get('expiry_date', '').strip()),
        bool(final_data.get('mfg_date', '').strip()),
        bool(final_data.get('manufacturer', '').strip()),
    ])
    return batch, expiry, completeness

def run_old_ocr(image_paths: list) -> dict:
    """
    Simulate OLD OCR behavior: Full-image extraction without region detection.
    This uses extract_fields() on full raw OCR text.
    """
    # Preprocess and extract text from FULL image (old approach)
    all_raw_text = []
    for img_path in image_paths:
        try:
            preprocessed = preprocess_image(img_path)
            raw_text = extract_text(preprocessed)
            all_raw_text.append(raw_text)
        except Exception as e:
            all_raw_text.append("")
    
    # Use OLD extraction method (full-image regex on combined text)
    combined_text = "\n".join(all_raw_text)
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

# Find test samples
samples_dir = Path("samples")
sample_folders = sorted([d for d in samples_dir.iterdir() if d.is_dir()])[:20]

if not sample_folders:
    print("✗ No test samples found")
    exit(1)

print(f"Testing {len(sample_folders)} sample(s) - comparing old vs new OCR\n")

comparisons = []
improvements = {'batch': 0, 'expiry': 0, 'overall': 0}

# Run comparison on each sample
for sample_idx, sample_folder in enumerate(sample_folders, 1):
    images = sorted(sample_folder.glob("*.jpg")) + sorted(sample_folder.glob("*.png"))
    if not images:
        continue
    
    image_paths = [str(img) for img in images]
    
    print(f"[{sample_idx:2d}] {sample_folder.name:6s} ", end="", flush=True)
    
    try:
        # Run OLD OCR (full-image)
        result_old = run_old_ocr(image_paths)
        old_batch, old_expiry, old_complete = evaluate_fields(result_old['final_data'])
        
        # Run NEW OCR (region-based) - this is now the default in process_medicine_images
        result_new = process_medicine_images(image_paths)
        new_batch, new_expiry, new_complete = evaluate_fields(result_new['final_data'])
        
        # Determine improvement
        batch_imp = "↑" if new_batch and not old_batch else ("↓" if not new_batch and old_batch else "=")
        expiry_imp = "↑" if new_expiry and not old_expiry else ("↓" if not new_expiry and old_expiry else "=")
        
        # Track improvements
        if new_batch and not old_batch:
            improvements['batch'] += 1
        if new_expiry and not old_expiry:
            improvements['expiry'] += 1
        if new_complete > old_complete:
            improvements['overall'] += 1
        
        print(f"| Old: B:{old_batch}→{old_expiry} {old_complete}/5 | New: B:{new_batch}→{new_expiry} {new_complete}/5 | Δ: {batch_imp}{expiry_imp}")
        
        comparisons.append({
            'sample': sample_folder.name,
            'old': {'batch': old_batch, 'expiry': old_expiry, 'completeness': old_complete},
            'new': {'batch': new_batch, 'expiry': new_expiry, 'completeness': new_complete},
            'improvement': {'batch': batch_imp, 'expiry': expiry_imp},
        })
        
    except Exception as e:
        print(f"✗ {e}")

# Print summary
print("\n" + "="*90)
print("BASELINE COMPARISON SUMMARY")
print("="*90 + "\n")

if comparisons:
    total = len(comparisons)
    
    # Calculate rates for OLD OCR
    old_batch_rate = sum(1 for c in comparisons if c['old']['batch']) / total
    old_expiry_rate = sum(1 for c in comparisons if c['old']['expiry']) / total
    old_avg_complete = sum(c['old']['completeness'] for c in comparisons) / total
    
    # Calculate rates for NEW OCR
    new_batch_rate = sum(1 for c in comparisons if c['new']['batch']) / total
    new_expiry_rate = sum(1 for c in comparisons if c['new']['expiry']) / total
    new_avg_complete = sum(c['new']['completeness'] for c in comparisons) / total
    
    # Calculate absolute improvements
    batch_gain = new_batch_rate - old_batch_rate
    expiry_gain = new_expiry_rate - old_expiry_rate
    complete_gain = new_avg_complete - old_avg_complete
    
    print("OLD OCR (Full-Image Extraction):")
    print(f"  • Batch detection rate:  {old_batch_rate:.0%}")
    print(f"  • Expiry detection rate: {old_expiry_rate:.0%}")
    print(f"  • Avg field completeness: {old_avg_complete:.1f}/5 ({old_avg_complete/5:.0%})")
    
    print(f"\nNEW OCR (Region-Based Extraction):")
    print(f"  • Batch detection rate:  {new_batch_rate:.0%}")
    print(f"  • Expiry detection rate: {new_expiry_rate:.0%}")
    print(f"  • Avg field completeness: {new_avg_complete:.1f}/5 ({new_avg_complete/5:.0%})")
    
    print(f"\nIMPROVEMENT:")
    print(f"  • Batch detection:  {old_batch_rate:.0%} → {new_batch_rate:.0%}  ({batch_gain:+.0%})")
    print(f"  • Expiry detection: {old_expiry_rate:.0%} → {new_expiry_rate:.0%}  ({expiry_gain:+.0%})")
    print(f"  • Completeness:     {old_avg_complete:.1f} → {new_avg_complete:.1f}  ({complete_gain:+.1f} fields, {complete_gain/5:+.0%})")
    
    print(f"\nSAMPLES WITH IMPROVEMENTS:")
    print(f"  • Batch improved:    {improvements['batch']} samples")
    print(f"  • Expiry improved:   {improvements['expiry']} samples")
    print(f"  • Overall improved:  {improvements['overall']} samples")
    
    # Save comparison report
    report_path = Path("baseline_comparison.json")
    report_path.write_text(json.dumps({
        'total_samples': total,
        'old_ocr': {
            'batch_rate': old_batch_rate,
            'expiry_rate': old_expiry_rate,
            'avg_completeness': old_avg_complete,
        },
        'new_ocr': {
            'batch_rate': new_batch_rate,
            'expiry_rate': new_expiry_rate,
            'avg_completeness': new_avg_complete,
        },
        'improvements': {
            'batch_gain': batch_gain,
            'expiry_gain': expiry_gain,
            'completeness_gain': complete_gain,
            'samples_with_batch_improvement': improvements['batch'],
            'samples_with_expiry_improvement': improvements['expiry'],
            'samples_with_overall_improvement': improvements['overall'],
        },
        'sample_details': comparisons,
    }, indent=2), encoding='utf-8')
    
    print(f"\n✓ Detailed comparison saved to: {report_path}")
    
    # Print recommendation
    print("\n" + "="*90)
    print("RECOMMENDATION")
    print("="*90 + "\n")
    
    if batch_gain > 0.15:
        print(f"✓ BATCH detection improved significantly (+{batch_gain:.0%})")
    elif batch_gain > 0:
        print(f"✓ BATCH detection improved slightly (+{batch_gain:.0%})")
    else:
        print(f"✗ BATCH detection did not improve ({batch_gain:+.0%})")
    
    if expiry_gain > 0.15:
        print(f"✓ EXPIRY detection improved significantly (+{expiry_gain:.0%})")
    elif expiry_gain > 0:
        print(f"✓ EXPIRY detection improved slightly (+{expiry_gain:.0%})")
    else:
        print(f"✗ EXPIRY detection did not improve ({expiry_gain:+.0%})")
    
    if complete_gain > 1:
        print(f"✓ Overall completeness improved significantly (+{complete_gain:.1f} fields)")
    elif complete_gain > 0:
        print(f"✓ Overall completeness improved slightly (+{complete_gain:.1f} fields)")
    else:
        print(f"✗ Overall completeness did not improve ({complete_gain:+.1f} fields)")

print("\n" + "="*90 + "\n")
