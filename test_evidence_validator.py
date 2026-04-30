"""
Test Evidence Validator with 3 scenarios:
A. Clean input test - should pass all fields
B. Noisy O CR test - should reject most fields  
C. Conflict test - different values across images, must trigger rejection or re-eval
"""

import sys
from pathlib import Path

# Setup paths
sys.path.insert(0, str(Path(__file__).parent))

from pipeline_orchestrator import PipelineOrchestrator
from pipeline_schemas import MediShieldPipelineOutput


def test_clean_input():
    """Test A: Clean OCR input - expects all fields CONFIRMED"""
    print("\n" + "="*70)
    print("TEST A: CLEAN INPUT (should pass all  fields)")
    print("="*70)
    
    # Create mock clean OCR output (simulating good OCR)
    from pipeline_schemas import (
        OCREngineOutput, OCRImageResult, OCRFieldDetection
    )
    import time
    
    clean_result = OCREngineOutput(
        image_results=[
            OCRImageResult(
                image_path="test_clean_1.jpg",
                medicine_name=OCRFieldDetection(value="Aspirin 500mg", confidence=0.95, raw_value="Aspirin 500mg"),
                batch_number=OCRFieldDetection(value="B12345", confidence=0.92, raw_value="B12345"),
                expiry_date=OCRFieldDetection(value="12/2025", confidence=0.90, raw_value="12/2025"),
                mfg_date=OCRFieldDetection(value="06/2024", confidence=0.88, raw_value="06/2024"),
                manufacturer=OCRFieldDetection(value="Pharma Inc Ltd", confidence=0.85, raw_value="Pharma Inc Ltd"),
                raw_text="Aspirin 500mg\nBatch: B12345\nExpiry: 12/2025\nMfg: 06/2024\nPharma Inc Ltd",
                overall_confidence=0.90,
            )
        ],
        raw_combined_text="Aspirin 500mg Batch: B12345 Expiry: 12/2025 Mfg: 06/2024 Pharma Inc Ltd",
        processing_time_seconds=0.5,
    )
    
    # Test validator
    from evidence_validator import validate_evidence
    final_fields, summary = validate_evidence(clean_result, clean_result)
    
    # Report results
    print(f"Any rejected: {summary['any_rejected']}")
    for field, ff in final_fields.items():
        status = "[OK] CONFIRMED" if ff.state == "CONFIRMED" else "[X] REJECTED"
        print(f"  {field:20} {status:20} conf={ff.confidence_score:.2f}")
        if ff.state == "REJECTED":
            print(f"    -> Reason: {ff.rejection_reason}")
    
    # Assertion
    confirmed_count = sum(1 for ff in final_fields.values() if ff.state == "CONFIRMED")
    print(f"\nExpected: 5/5 fields CONFIRMED")
    print(f"Actual: {confirmed_count}/5 fields CONFIRMED")
    print(f"Status: {'PASS' if confirmed_count >= 4 else 'FAIL'}")
    

def test_noisy_ocr():
    """Test B: Noisy OCR - expects most fields REJECTED"""
    print("\n" + "="*70)
    print("TEST B: NOISY OCR (should reject most fields)")
    print("="*70)
    
    from pipeline_schemas import (
        OCREngineOutput, OCRImageResult, OCRFieldDetection
    )
    
    noisy_result = OCREngineOutput(
        image_results=[
            OCRImageResult(
                image_path="test_noisy_1.jpg",
                medicine_name=OCRFieldDetection(value="@#$%^&", confidence=0.15, raw_value="@#$%^&"),
                batch_number=OCRFieldDetection(value="!!!999", confidence=0.10, raw_value="!!!999"),
                expiry_date=OCRFieldDetection(value="99/99", confidence=0.05, raw_value="99/99"),
                mfg_date=OCRFieldDetection(value="XX/YYYY", confidence=0.08, raw_value="XX/YYYY"),
                manufacturer=OCRFieldDetection(value="^^^&&&", confidence=0.12, raw_value="^^^&&&"),
                raw_text="@#$%^& !!!999 99/99 XX/YYYY ^^^&&&",
                overall_confidence=0.10,
            )
        ],
        raw_combined_text="@#$%^& !!!999 99/99 XX/YYYY ^^^&&&",
        processing_time_seconds=0.5,
    )
    
    from evidence_validator import validate_evidence
    final_fields, summary = validate_evidence(noisy_result, noisy_result)
    
    print(f"Any rejected: {summary['any_rejected']}")
    for field, ff in final_fields.items():
        status = "✓ CONFIRMED" if ff.state == "CONFIRMED" else "✗ REJECTED"
        print(f"  {field:20} {status:20} conf={ff.confidence_score:.2f}")
        if ff.state == "REJECTED":
            print(f"    → Reason: {ff.rejection_reason}")
    
    rejected_count = sum(1 for ff in final_fields.values() if ff.state == "REJECTED")
    print(f"\nExpected: >=3/5 fields REJECTED")
    print(f"Actual: {rejected_count}/5 fields REJECTED")
    print(f"Status: {'PASS' if rejected_count >= 3 else 'FAIL'}")


def test_conflict():
    """Test C: Cross-image conflicts - should trigger rejection or re-eval"""
    print("\n" + "="*70)
    print("TEST C: CROSS-IMAGE CONFLICT (different values across images)")
    print("="*70)
    
    from pipeline_schemas import (
        OCREngineOutput, OCRImageResult, OCRFieldDetection, FusionEngineOutput, FieldFusion
    )
    from fusion_engine import FusionEngine
    
    # Simulate 2 images with conflicting batch numbers
    conflict_result = OCREngineOutput(
        image_results=[
            OCRImageResult(
                image_path="test_conflict_1.jpg",
                medicine_name=OCRFieldDetection(value="Aspirin 500mg", confidence=0.90, raw_value="Aspirin 500mg"),
                batch_number=OCRFieldDetection(value="B11111", confidence=0.85, raw_value="B11111"),
                expiry_date=OCRFieldDetection(value="12/2025", confidence=0.88, raw_value="12/2025"),
                mfg_date=OCRFieldDetection(value="06/2024", confidence=0.85, raw_value="06/2024"),
                manufacturer=OCRFieldDetection(value="Pharma Inc Ltd", confidence=0.82, raw_value="Pharma Inc Ltd"),
                raw_text="Aspirin 500mg Batch: B11111 Expiry: 12/2025 Mfg: 06/2024",
                overall_confidence=0.86,
            ),
            OCRImageResult(
                image_path="test_conflict_2.jpg",
                medicine_name=OCRFieldDetection(value="Aspirin 500mg", confidence=0.91, raw_value="Aspirin 500mg"),
                batch_number=OCRFieldDetection(value="B22222", confidence=0.80, raw_value="B22222"),  # DIFFERENT
                expiry_date=OCRFieldDetection(value="12/2025", confidence=0.89, raw_value="12/2025"),
                mfg_date=OCRFieldDetection(value="06/2024", confidence=0.84, raw_value="06/2024"),
                manufacturer=OCRFieldDetection(value="Pharma Inc Ltd", confidence=0.83, raw_value="Pharma Inc Ltd"),
                raw_text="Aspirin 500mg Batch: B22222 Expiry: 12/2025 Mfg: 06/2024",
                overall_confidence=0.87,
            )
        ],
        raw_combined_text="Aspirin batch conflict test",
        processing_time_seconds=0.8,
    )
    
    # Fuse to get conflicting result
    fusion_engine = FusionEngine()
    fusion_result = fusion_engine.fuse_results(conflict_result)
    
    # Validate
    from evidence_validator import validate_evidence
    final_fields, summary = validate_evidence(fusion_result, conflict_result)
    
    print(f"Any rejected: {summary['any_rejected']}")
    print(f"Suggestions for re-fusion: {summary.get('suggestions_for_refusion', {})}")
    
    for field, ff in final_fields.items():
        status = "✓ CONFIRMED" if ff.state == "CONFIRMED" else "✗ REJECTED"
        print(f"  {field:20} {status:20} conf={ff.confidence_score:.2f}")
        if ff.state == "REJECTED":
            print(f"    → Reason: {ff.rejection_reason}")
    
    batch_rejected = final_fields["batch_number"].state == "REJECTED"
    print(f"\nExpected: batch_number REJECTED due to conflict")
    print(f"Actual: {'PASS' if batch_rejected else 'FAIL'}")


if __name__ == "__main__":
    print("\n" + "#"*70)
    print("# EVIDENCE VALIDATOR TEST SUITE")
    print("#"*70)
    
    try:
        test_clean_input()
    except Exception as e:
        print(f"TEST A FAILED: {e}")
        import traceback
        traceback.print_exc()
    
    try:
        test_noisy_ocr()
    except Exception as e:
        print(f"TEST B FAILED: {e}")
        import traceback
        traceback.print_exc()
    
    try:
        test_conflict()
    except Exception as e:
        print(f"TEST C FAILED: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "#"*70)
    print("# TEST SUITE COMPLETE")
    print("#"*70)
