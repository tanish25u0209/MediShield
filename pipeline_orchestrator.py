"""
Pipeline Orchestrator - Modular end-to-end execution flow.

Coordinates all engines:
1. OCR Engine - Extract text and fields
2. Fusion Engine - Multi-image consensus
3. Validation Engine - Data quality checks
4. Classifier Engine - Packaging form detection
5. Risk Engine V2 - Comprehensive risk scoring

Output: Structured MediShieldPipelineOutput with full traceability.
"""

import time
from typing import List, Dict, Any, Optional
from datetime import datetime

from pipeline_schemas import (
    MediShieldPipelineOutput,
    PipelineExecutionTrace,
    RiskLevel,
    PackagingForm,
    convert_to_legacy_format,
    FinalField,
)

from ocr_engine import OCREngine
from fusion_engine import FusionEngine
from validation_engine import ValidationEngine
from classifier_engine import ClassifierEngine
from risk_engine_v2 import RiskEngine
from evidence_validator import validate_evidence
from medishield_ocr import process_medicine_images_with_ocr_core  # NEW: OCR gateway
from copy import deepcopy


class PipelineOrchestrator:
    """Orchestrates modular pipeline execution."""

    def __init__(self, classifier_model_path: Optional[str] = None):
        """Initialize orchestrator with all engines."""
        # NOTE: OCREngine is NO LONGER USED - replaced with process_medicine_images_with_ocr_core()
        # which enforces the 2-call Tesseract contract
        self.fusion_engine = FusionEngine()
        self.validation_engine = ValidationEngine()
        self.classifier_engine = ClassifierEngine(classifier_model_path)
        self.risk_engine = RiskEngine()

        self.execution_trace: List[PipelineExecutionTrace] = []

    def process_medicine_images(self, image_paths: List[str]) -> MediShieldPipelineOutput:
        """
        Process one or more images of the same medicine package.

        Returns: Complete structured pipeline output with traceability.
        """
        start_time = time.time()
        self.execution_trace = []

        try:
            # Stage 1: OCR
            ocr_result = self._run_stage_ocr(image_paths)

            # Stage 2: Fusion
            fusion_result = self._run_stage_fusion(ocr_result)

            # Stage 2.5: Evidence Validator (strict truth verification)
            final_fields_map, ev_summary = validate_evidence(fusion_result, ocr_result)

            # TIGHTENED RE-EVALUATION: Only re-fuse if strategically justified
            # Criteria: Cross-image conflicts OR rejection pattern clustering
            suggestions = ev_summary.get("suggestions_for_refusion", {})
            should_refuse = False
            
            # Check 1: Are there cross-image conflicts (conflicting_values)?
            has_conflicts = any(info.get("conflicting_values") for info in suggestions.values())
            
            # Check 2: Is there a rejection cluster (multiple fields rejected)?
            rejection_count = sum(1 for ff in final_fields_map.values() if ff.state == "REJECTED")
            has_rejection_cluster = rejection_count >= 3  # Arbitrary threshold: 3+ fields
            
            if has_conflicts or has_rejection_cluster:
                should_refuse = True

            if should_refuse and suggestions:
                # Build a filtered copy of OCR results per suggestions
                filtered_ocr = deepcopy(ocr_result)
                for field, info in suggestions.items():
                    conflicting = info.get("conflicting_values", [])
                    for imgres in filtered_ocr.image_results:
                        det = getattr(imgres, field, None)
                        if det is None or det.value is None:
                            continue
                        if det.value.strip().upper() in [c.strip().upper() for c in conflicting]:
                            # suppress this detection for re-fusion
                            det.value = None
                            det.confidence = 0.0
                            det.raw_value = None

                # Re-run fusion on filtered OCR (ONLY 1 PASS ALLOWED)
                re_fusion_result = self.fusion_engine.fuse_results(filtered_ocr)

                # Re-validate evidence against re-fused output
                re_final_fields_map, re_ev_summary = validate_evidence(re_fusion_result, filtered_ocr)

                # Merge results: prefer CONFIRMED from re-eval, otherwise keep original
                for k, v in re_final_fields_map.items():
                    if v.state == "CONFIRMED":
                        final_fields_map[k] = v
                # Replace fusion_result with re-fusion for final output (reflects suppression)
                fusion_result = re_fusion_result

            # Stage 3: Validation
            validation_result = self._run_stage_validation(fusion_result)

            # Stage 4: Classification
            classifier_result = self._run_stage_classification(image_paths)

            # Stage 5: Risk Assessment
            risk_result = self._run_stage_risk(
                fusion_result, validation_result, classifier_result, len(image_paths)
            )

            # Consolidate final outputs using FinalField produced by evidence validator
            # If validator not run for some reason, fall back to fused strings
            try:
                final_data = {k: (v if isinstance(v, FinalField) else FinalField(value=v, state=("CONFIRMED" if v else "REJECTED"), confidence_score=1.0 if v else 0.0)) for k, v in final_fields_map.items()}
            except Exception:
                final_data = {
                    "medicine_name": fusion_result.medicine_name.final_value,
                    "batch_number": fusion_result.batch_number.final_value,
                    "expiry_date": fusion_result.expiry_date.final_value,
                    "mfg_date": fusion_result.mfg_date.final_value,
                    "manufacturer": fusion_result.manufacturer.final_value,
                }

            final_form = classifier_result.final_form
            final_risk_score = risk_result.risk_score
            final_risk_level = risk_result.risk_level

            total_time = time.time() - start_time

            # Build complete output
            pipeline_output = MediShieldPipelineOutput(
                ocr_result=ocr_result,
                fusion_result=fusion_result,
                validation_result=validation_result,
                classification_result=classifier_result,
                risk_result=risk_result,
                final_data=final_data,
                final_form=final_form,
                final_risk_score=final_risk_score,
                final_risk_level=final_risk_level,
                execution_trace=self.execution_trace,
                images_processed=len(image_paths),
                total_processing_time_seconds=total_time,
                backward_compatibility_data=convert_to_legacy_format(
                    # Create temporary output for conversion
                    MediShieldPipelineOutput(
                        ocr_result=ocr_result,
                        fusion_result=fusion_result,
                        validation_result=validation_result,
                        classification_result=classifier_result,
                        risk_result=risk_result,
                        final_data=final_data,
                        final_form=final_form,
                        final_risk_score=final_risk_score,
                        final_risk_level=final_risk_level,
                        execution_trace=self.execution_trace,
                        images_processed=len(image_paths),
                        total_processing_time_seconds=total_time,
                    )
                ),
            )

            return pipeline_output

        except Exception as e:
            # Log error and return partial result
            self.execution_trace.append(
                PipelineExecutionTrace(
                    stage="ERROR",
                    timestamp=datetime.now().isoformat(),
                    input_summary={"image_count": len(image_paths)},
                    output_summary={},
                    processing_time_seconds=time.time() - start_time,
                    errors=[str(e)],
                )
            )
            raise

    # ========================================================================
    # STAGE RUNNERS
    # ========================================================================

    def _run_stage_ocr(self, image_paths: List[str]) -> Any:
        """Run OCR stage using deterministic ocr_core() gateway (2 Tesseract calls per image)."""
        start_time = time.time()

        try:
            # Use the OCR contract gateway - enforces exactly 2 pytesseract calls per image
            result = process_medicine_images_with_ocr_core(image_paths)

            self.execution_trace.append(
                PipelineExecutionTrace(
                    stage="ocr",
                    timestamp=datetime.now().isoformat(),
                    input_summary={"image_count": len(image_paths)},
                    output_summary={
                        "images_processed": len(result.image_results),
                        "avg_confidence": sum(
                            r.overall_confidence for r in result.image_results
                        )
                        / len(result.image_results)
                        if result.image_results
                        else 0.0,
                    },
                    processing_time_seconds=result.processing_time_seconds,
                    errors=[],
                )
            )

            return result

        except Exception as e:
            self.execution_trace.append(
                PipelineExecutionTrace(
                    stage="ocr",
                    timestamp=datetime.now().isoformat(),
                    input_summary={"image_count": len(image_paths)},
                    output_summary={},
                    processing_time_seconds=time.time() - start_time,
                    errors=[str(e)],
                )
            )
            raise

    def _run_stage_fusion(self, ocr_result: Any) -> Any:
        """Run fusion stage."""
        start_time = time.time()

        try:
            result = self.fusion_engine.fuse_results(ocr_result)

            self.execution_trace.append(
                PipelineExecutionTrace(
                    stage="fusion",
                    timestamp=datetime.now().isoformat(),
                    input_summary={"ocr_images": len(ocr_result.image_results)},
                    output_summary={
                        "consistency_score": result.consistency_score,
                        "overall_confidence": result.overall_field_confidence,
                        "conflicts_detected": len(result.conflicts_detected),
                    },
                    processing_time_seconds=result.processing_time_seconds,
                    errors=[],
                )
            )

            return result

        except Exception as e:
            self.execution_trace.append(
                PipelineExecutionTrace(
                    stage="fusion",
                    timestamp=datetime.now().isoformat(),
                    input_summary={},
                    output_summary={},
                    processing_time_seconds=time.time() - start_time,
                    errors=[str(e)],
                )
            )
            raise

    def _run_stage_validation(self, fusion_result: Any) -> Any:
        """Run validation stage."""
        start_time = time.time()

        try:
            result = self.validation_engine.validate(fusion_result)

            self.execution_trace.append(
                PipelineExecutionTrace(
                    stage="validation",
                    timestamp=datetime.now().isoformat(),
                    input_summary={"fused_fields": 5},
                    output_summary={
                        "is_valid": result.is_valid,
                        "completeness": result.completeness_score,
                        "data_quality": result.data_quality_score,
                        "issue_count": len(result.issues),
                    },
                    processing_time_seconds=result.processing_time_seconds,
                    errors=[],
                )
            )

            return result

        except Exception as e:
            self.execution_trace.append(
                PipelineExecutionTrace(
                    stage="validation",
                    timestamp=datetime.now().isoformat(),
                    input_summary={},
                    output_summary={},
                    processing_time_seconds=time.time() - start_time,
                    errors=[str(e)],
                )
            )
            raise

    def _run_stage_classification(self, image_paths: List[str]) -> Any:
        """Run classification stage."""
        start_time = time.time()

        try:
            result = self.classifier_engine.classify_images(image_paths)

            self.execution_trace.append(
                PipelineExecutionTrace(
                    stage="classification",
                    timestamp=datetime.now().isoformat(),
                    input_summary={"image_count": len(image_paths)},
                    output_summary={
                        "predicted_form": result.final_form.value,
                        "confidence": result.confidence,
                    },
                    processing_time_seconds=result.processing_time_seconds,
                    errors=[],
                )
            )

            return result

        except Exception as e:
            self.execution_trace.append(
                PipelineExecutionTrace(
                    stage="classification",
                    timestamp=datetime.now().isoformat(),
                    input_summary={},
                    output_summary={},
                    processing_time_seconds=time.time() - start_time,
                    errors=[str(e)],
                )
            )
            raise

    def _run_stage_risk(
        self, fusion_result: Any, validation_result: Any, classifier_result: Any, num_images: int
    ) -> Any:
        """Run risk assessment stage."""
        start_time = time.time()

        try:
            result = self.risk_engine.calculate_risk(
                fusion_result, validation_result, classifier_result, num_images
            )

            self.execution_trace.append(
                PipelineExecutionTrace(
                    stage="risk",
                    timestamp=datetime.now().isoformat(),
                    input_summary={
                        "fusion_consistency": fusion_result.consistency_score,
                        "validation_quality": validation_result.data_quality_score,
                    },
                    output_summary={
                        "risk_score": result.risk_score,
                        "risk_level": result.risk_level.value,
                        "confidence": result.confidence_level.value,
                    },
                    processing_time_seconds=result.processing_time_seconds,
                    errors=[],
                )
            )

            return result

        except Exception as e:
            self.execution_trace.append(
                PipelineExecutionTrace(
                    stage="risk",
                    timestamp=datetime.now().isoformat(),
                    input_summary={},
                    output_summary={},
                    processing_time_seconds=time.time() - start_time,
                    errors=[str(e)],
                )
            )
            raise
