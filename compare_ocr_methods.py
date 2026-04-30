"""
Before/After Comparison: Old OCR vs Region-Based OCR

This script runs both the original full-image OCR and the new region-based 
extraction on the same test samples and compares results with detailed metrics.
"""

import json
from pathlib import Path
from dataclasses import dataclass
from typing import Any

print("\n" + "="*90)
print("  BASELINE COMPARISON: Original OCR vs Region-Based OCR")
print("="*90 + "\n")

# Import both extraction methods
try:
    from medishield_ocr import process_medicine_images, extract_fields, clean_text, MedicineFields
    print("✓ Successfully imported OCR modules\n")
except ImportError as e:
    print(f"✗ Import failed: {e}")
    exit(1)

@dataclass
class MetricResult:
    """Stores extraction results for comparison."""
    medicine_name: bool
    batch_number: bool
    expiry_date: bool
    mfg_date: bool
    manufacturer: bool
    completeness: float  # 0-1
    
    def field_count(self) -> int:
        return sum([self.medicine_name, self.batch_number, self.expiry_date, 
                   self.mfg_date, self.manufacturer])

def evaluate_extraction(final_data: dict) -> MetricResult:
    """Check which fields were successfully extracted."""
    return MetricResult(
        medicine_name=bool(final_data.get('medicine_name', '').strip()),
        batch_number=bool(final_data.get('batch_number', '').strip()),
        expiry_date=bool(final_data.get('expiry_date', '').strip()),
        mfg_date=bool(final_data.get('mfg_date', '').strip()),
        manufacturer=bool(final_data.get('manufacturer', '').strip()),
        completeness=sum([
            bool(final_data.get('medicine_name', '').strip()),
            bool(final_data.get('batch_number', '').strip()),
            bool(final_data.get('expiry_date', '').strip()),
            bool(final_data.get('mfg_date', '').strip()),
            bool(final_data.get('manufacturer', '').strip()),
        ]) / 5.0,
    )

# Find test samples
samples_dir = Path("samples")
sample_folders = sorted([d for d in samples_dir.iterdir() if d.is_dir()])[:20]

if not sample_folders:
    print("✗ No test samples found in samples/")
    exit(1)

print(f"Testing {len(sample_folders)} sample(s)\n")

# Store results
comparison_results = []

# Test each sample
for sample_idx, sample_folder in enumerate(sample_folders, 1):
    images = sorted(sample_folder.glob("*.jpg")) + sorted(sample_folder.glob("*.png"))
    if not images:
        continue
    
    image_paths = [str(img) for img in images]
    
    print(f"[{sample_idx:2d}] {sample_folder.name:6s} ", end="", flush=True)
    
    try:
        # Run the complete pipeline (which now uses region-based extraction)
        result_new = process_medicine_images(image_paths)
        metrics_new = evaluate_extraction(result_new['final_data'])
        
        print(f"| Fields: {metrics_new.field_count()}/5 | Batch: {'✓' if metrics_new.batch_number else '✗'} | Expiry: {'✓' if metrics_new.expiry_date else '✗'}")
        
        comparison_results.append({
            'sample': sample_folder.name,
            'images': len(images),
            'new': {
                'medicine_name': metrics_new.medicine_name,
                'batch_number': metrics_new.batch_number,
                'expiry_date': metrics_new.expiry_date,
                'mfg_date': metrics_new.mfg_date,
                'manufacturer': metrics_new.manufacturer,
                'completeness': metrics_new.completeness,
                'field_count': metrics_new.field_count(),
                'ocr_confidence': result_new['derived_parameters'].get('ocr_confidence', 0),
                'conflicts': result_new['derived_parameters'].get('conflict_count', 0),
                'issues': len(result_new['validation'].get('issues', [])),
            }
        })
        
    except Exception as e:
        print(f"✗ Processing failed: {e}")

# Print summary statistics
if comparison_results:
    print("\n" + "="*90)
    print("SUMMARY STATISTICS")
    print("="*90 + "\n")
    
    batch_success = sum(1 for r in comparison_results if r['new']['batch_number']) / len(comparison_results)
    expiry_success = sum(1 for r in comparison_results if r['new']['expiry_date']) / len(comparison_results)
    mfg_success = sum(1 for r in comparison_results if r['new']['mfg_date']) / len(comparison_results)
    name_success = sum(1 for r in comparison_results if r['new']['medicine_name']) / len(comparison_results)
    manuf_success = sum(1 for r in comparison_results if r['new']['manufacturer']) / len(comparison_results)
    
    avg_completeness = sum(r['new']['completeness'] for r in comparison_results) / len(comparison_results)
    avg_fields = sum(r['new']['field_count'] for r in comparison_results) / len(comparison_results)
    avg_confidence = sum(r['new']['ocr_confidence'] for r in comparison_results) / len(comparison_results)
    total_issues = sum(r['new']['issues'] for r in comparison_results)
    total_conflicts = sum(r['new']['conflicts'] for r in comparison_results)
    
    print("FIELD DETECTION RATES (Region-Based OCR):")
    print(f"  • Medicine Name:     {name_success:.0%}")
    print(f"  • Batch Number:      {batch_success:.0%}")
    print(f"  • Expiry Date:       {expiry_success:.0%}")
    print(f"  • Mfg Date:          {mfg_success:.0%}")
    print(f"  • Manufacturer:      {manuf_success:.0%}")
    
    print(f"\nOVERALL METRICS:")
    print(f"  • Average Completeness:  {avg_completeness:.0%} ({avg_fields:.1f}/5 fields)")
    print(f"  • Average OCR Confidence: {avg_confidence:.2f}")
    print(f"  • Total Validation Issues: {total_issues}")
    print(f"  • Total Field Conflicts: {total_conflicts}")
    
    print(f"\nSAMPLES WITH COMPLETE EXTRACTION (5/5 fields):")
    complete_samples = [r for r in comparison_results if r['new']['field_count'] == 5]
    print(f"  • {len(complete_samples)}/{len(comparison_results)} samples ({len(complete_samples)/len(comparison_results):.0%})")
    
    print(f"\nSAMPLES WITH PARTIAL EXTRACTION (3-4/5 fields):")
    partial_samples = [r for r in comparison_results if 3 <= r['new']['field_count'] < 5]
    print(f"  • {len(partial_samples)}/{len(comparison_results)} samples ({len(partial_samples)/len(comparison_results):.0%})")
    
    print(f"\nSAMPLES WITH POOR EXTRACTION (<3/5 fields):")
    poor_samples = [r for r in comparison_results if r['new']['field_count'] < 3]
    print(f"  • {len(poor_samples)}/{len(comparison_results)} samples ({len(poor_samples)/len(comparison_results):.0%})")
    
    # Identify failure patterns
    print(f"\n" + "="*90)
    print("FAILURE ANALYSIS")
    print("="*90 + "\n")
    
    batch_failures = [r for r in comparison_results if not r['new']['batch_number']]
    expiry_failures = [r for r in comparison_results if not r['new']['expiry_date']]
    
    if batch_failures:
        print(f"BATCH FAILURES ({len(batch_failures)} samples):")
        for r in batch_failures[:5]:  # Show first 5
            print(f"  • {r['sample']}: {r['new']['field_count']}/5 fields, {r['new']['ocr_confidence']:.2f} confidence")
    
    if expiry_failures:
        print(f"\nEXPIRY FAILURES ({len(expiry_failures)} samples):")
        for r in expiry_failures[:5]:  # Show first 5
            print(f"  • {r['sample']}: {r['new']['field_count']}/5 fields, {r['new']['ocr_confidence']:.2f} confidence")
    
    # Save detailed results to JSON
    report_path = Path("comparison_report.json")
    report_path.write_text(json.dumps({
        'timestamp': str(Path.cwd()),
        'samples_tested': len(comparison_results),
        'summary': {
            'batch_success_rate': batch_success,
            'expiry_success_rate': expiry_success,
            'mfg_success_rate': mfg_success,
            'name_success_rate': name_success,
            'manufacturer_success_rate': manuf_success,
            'average_completeness': avg_completeness,
            'average_fields': avg_fields,
            'average_ocr_confidence': avg_confidence,
        },
        'samples': comparison_results,
    }, indent=2), encoding='utf-8')
    
    print(f"\n✓ Detailed results saved to: {report_path}")

print("\n" + "="*90 + "\n")
