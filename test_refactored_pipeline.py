"""
Integration Test - Validates modular pipeline architecture.

Demonstrates:
1. Modular execution flow
2. Structured output schema
3. Backward compatibility
4. Traceability and logging
5. Per-stage confidence and scoring
"""

import json
import sys
from pathlib import Path
from typing import List

# Import new modular pipeline
from medishield_pipeline_refactored import MediShieldPipelineAdapter
from pipeline_schemas import (
    MediShieldPipelineOutput,
    RiskLevel,
    ConfidenceLevel,
    PackagingForm,
)


def validate_structured_output(output: MediShieldPipelineOutput) -> bool:
    """Validate that output meets structural requirements."""
    errors = []

    # Check OCR output
    if output.ocr_result is None or not output.ocr_result.image_results:
        errors.append("OCR result is empty or missing")

    # Check fusion output
    if output.fusion_result is None:
        errors.append("Fusion result is missing")
    else:
        if output.fusion_result.batch_number is None:
            errors.append("Fusion result missing batch_number field")
        if output.fusion_result.expiry_date is None:
            errors.append("Fusion result missing expiry_date field")

    # Check validation output
    if output.validation_result is None:
        errors.append("Validation result is missing")
    else:
        if not isinstance(output.validation_result.is_valid, bool):
            errors.append("Validation result is_valid is not boolean")

    # Check classification output
    if output.classification_result is None:
        errors.append("Classification result is missing")
    else:
        if not isinstance(output.classification_result.final_form, PackagingForm):
            errors.append("Classification result final_form is not PackagingForm")

    # Check risk output
    if output.risk_result is None:
        errors.append("Risk result is missing")
    else:
        if not isinstance(output.risk_result.risk_level, RiskLevel):
            errors.append("Risk result risk_level is not RiskLevel")
        if not isinstance(output.risk_result.confidence_level, ConfidenceLevel):
            errors.append("Risk result confidence_level is not ConfidenceLevel")
        if not (0 <= output.risk_result.risk_score <= 100):
            errors.append(f"Risk score {output.risk_result.risk_score} is out of range [0, 100]")

    # Check final data
    if output.final_data is None:
        errors.append("Final data is missing")

    # Check execution trace
    if not output.execution_trace:
        errors.append("Execution trace is empty")

    if errors:
        print("❌ VALIDATION FAILED:")
        for error in errors:
            print(f"   - {error}")
        return False

    print("✅ VALIDATION PASSED: Output structure is correct")
    return True


def print_output_summary(output: MediShieldPipelineOutput):
    """Print human-readable summary of pipeline output."""
    print("\n" + "=" * 70)
    print(" MEDISHIELD REFACTORED PIPELINE - EXECUTION SUMMARY")
    print("=" * 70)

    # Final predictions
    print("\n📊 FINAL PREDICTIONS:")
    print(f"  Medicine: {output.final_data.get('medicine_name', 'N/A')}")
    print(f"  Batch #: {output.final_data.get('batch_number', 'N/A')}")
    print(f"  Expiry: {output.final_data.get('expiry_date', 'N/A')}")
    print(f"  Mfg Date: {output.final_data.get('mfg_date', 'N/A')}")
    print(f"  Manufacturer: {output.final_data.get('manufacturer', 'N/A')}")

    # Risk Assessment
    print("\n⚠️  RISK ASSESSMENT:")
    print(f"  Risk Score: {output.final_risk_score}/100")
    print(f"  Risk Level: {output.final_risk_level.value}")
    print(f"  Confidence: {output.risk_result.confidence_level.value}")

    # Packaging Classification
    print("\n📦 PACKAGING CLASSIFICATION:")
    print(f"  Form: {output.classification_result.final_form.value}")
    print(f"  Confidence: {output.classification_result.confidence:.0%}")

    # Validation Summary
    print("\n✔️  VALIDATION:")
    print(f"  Valid: {'Yes' if output.validation_result.is_valid else 'No'}")
    print(f"  Completeness: {output.validation_result.completeness_score:.0%}")
    print(f"  Data Quality: {output.validation_result.data_quality_score:.0%}")
    if output.validation_result.issues:
        print(f"  Issues: {len(output.validation_result.issues)}")
        for issue in output.validation_result.issues[:3]:
            print(f"    - [{issue.severity}] {issue.message}")

    # Fusion Consistency
    print("\n🔗 MULTI-IMAGE FUSION:")
    print(f"  Consistency Score: {output.fusion_result.consistency_score:.0%}")
    print(f"  Field Confidence: {output.fusion_result.overall_field_confidence:.0%}")
    if output.fusion_result.conflicts_detected:
        print(f"  Conflicts: {len(output.fusion_result.conflicts_detected)}")

    # Performance
    print("\n⏱️  PERFORMANCE:")
    print(f"  Images Processed: {output.images_processed}")
    print(f"  Total Time: {output.total_processing_time_seconds:.2f}s")

    # Execution Trace
    print("\n📋 EXECUTION TRACE:")
    for trace in output.execution_trace:
        status = "❌" if trace.errors else "✅"
        print(f"  {status} {trace.stage.upper()}: {trace.processing_time_seconds:.3f}s")
        if trace.errors:
            for error in trace.errors:
                print(f"      Error: {error}")

    # Risk Signals
    print("\n🎯 RISK SIGNALS:")
    for signal in output.risk_result.signal_components:
        print(f"  • {signal.name.upper()}: {signal.raw_value:.0%} (weight: {signal.weight:.0%})")

    # Risk Explanation
    if output.risk_result.explanation:
        print("\n💡 RISK EXPLANATION:")
        for item in output.risk_result.explanation[:5]:
            print(f"  • {item.reason}")
            if item.penalty_or_boost != 0:
                sign = "+" if item.penalty_or_boost > 0 else ""
                print(f"    {sign}{item.penalty_or_boost} points [{item.severity}]")

    print("\n" + "=" * 70 + "\n")


def test_with_sample_images(image_dir: str = "medishield_data/raw"):
    """Test pipeline with actual sample data."""
    print("\n🔍 Testing refactored pipeline with sample images...")

    image_dir_path = Path(image_dir)
    if not image_dir_path.exists():
        print(f"⚠️  Sample directory not found: {image_dir}")
        print("   To test, provide path to directory with sample images")
        return False

    # Find sample images
    sample_images = list(image_dir_path.glob("*/front.png")) + list(
        image_dir_path.glob("*/front.jpg")
    )

    if not sample_images:
        print(f"⚠️  No sample images found in {image_dir}")
        return False

    print(f"Found {len(sample_images)} sample images")

    # Process first sample
    test_image = str(sample_images[0])
    print(f"\n📷 Processing: {test_image}")

    try:
        adapter = MediShieldPipelineAdapter()
        output = adapter.process_medicine_images_new([test_image])

        # Validate structure
        if not validate_structured_output(output):
            return False

        # Print summary
        print_output_summary(output)

        # Test backward compatibility
        print("\n🔄 Testing backward compatibility...")
        legacy_output = adapter.process_medicine_images([test_image])

        # Verify legacy output has expected keys
        required_legacy_keys = ["final_data", "risk_score", "risk_level"]
        missing_keys = [k for k in required_legacy_keys if k not in legacy_output]

        if missing_keys:
            print(f"❌ Legacy output missing keys: {missing_keys}")
            return False

        print("✅ Backward compatibility check passed")

        # Test JSON serialization
        print("\n📄 Testing JSON serialization...")
        try:
            json_output = output.to_json()
            json.loads(json_output)  # Verify valid JSON
            print(f"✅ JSON serialization successful ({len(json_output)} bytes)")
        except Exception as e:
            print(f"❌ JSON serialization failed: {e}")
            return False

        return True

    except Exception as e:
        print(f"❌ Pipeline execution failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def print_architecture_diagram():
    """Print text diagram of refactored architecture."""
    print("\n" + "=" * 70)
    print(" REFACTORED PIPELINE ARCHITECTURE")
    print("=" * 70)
    print("""
  IMAGE INPUTS
      ↓
  ┌─────────────────────────────────────────────────────────────┐
  │                    PIPELINE ORCHESTRATOR                     │
  └─────────────────────────────────────────────────────────────┘
      ↓
  ┌─────────────────────────────────────────────────────────────┐
  │  1️⃣  OCR ENGINE                                              │
  │     • Adaptive preprocessing                                │
  │     • Multi-PSM Tesseract extraction                         │
  │     • Per-field confidence scoring                           │
  │     → Output: OCREngineOutput                               │
  └─────────────────────────────────────────────────────────────┘
      ↓
  ┌─────────────────────────────────────────────────────────────┐
  │  2️⃣  FUSION ENGINE                                           │
  │     • Weighted majority voting                              │
  │     • Conflict detection                                     │
  │     • Consistency scoring                                    │
  │     → Output: FusionEngineOutput                            │
  └─────────────────────────────────────────────────────────────┘
      ↓
  ┌─────────────────────────────────────────────────────────────┐
  │  3️⃣  VALIDATION ENGINE                                       │
  │     • Required field checks                                 │
  │     • Date format and logic validation                      │
  │     • Completeness scoring                                  │
  │     → Output: ValidationEngineOutput                        │
  └─────────────────────────────────────────────────────────────┘
      ↓
  ┌─────────────────────────────────────────────────────────────┐
  │  4️⃣  CLASSIFIER ENGINE                                       │
  │     • Packaging form detection (MobileNetV2)                │
  │     • Multi-image consensus                                 │
  │     → Output: ClassifierEngineOutput                        │
  └─────────────────────────────────────────────────────────────┘
      ↓
  ┌─────────────────────────────────────────────────────────────┐
  │  5️⃣  RISK ENGINE V2                                          │
  │     • Weighted multi-component scoring                      │
  │     • Risk level classification                             │
  │     • Detailed explanations                                 │
  │     → Output: RiskEngineOutput                              │
  └─────────────────────────────────────────────────────────────┘
      ↓
  ┌─────────────────────────────────────────────────────────────┐
  │  STRUCTURED OUTPUT (MediShieldPipelineOutput)                │
  │  • All engine outputs                                        │
  │  • Final predictions                                         │
  │  • Execution trace & logging                                │
  │  • Backward compatibility layer                              │
  └─────────────────────────────────────────────────────────────┘

KEY IMPROVEMENTS:
  ✅ Modular: Each engine independently testable
  ✅ Structured: Type-safe dataclass schemas
  ✅ Traceable: Full execution trace per stage
  ✅ Robust: Per-field confidence, weighted scoring
  ✅ Compatible: Legacy code still works
""")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    print_architecture_diagram()

    # Run integration test
    success = test_with_sample_images()

    if success:
        print("\n✅ ALL INTEGRATION TESTS PASSED")
        print("\nTo use the refactored pipeline:")
        print("  1. For new code: import & use new modular engines")
        print("  2. For existing code: backward compatible adapter works transparently")
        print("  3. For analysis: use MediShieldPipelineOutput.to_json() for full traceability")
        sys.exit(0)
    else:
        print("\n❌ INTEGRATION TEST FAILED")
        sys.exit(1)
