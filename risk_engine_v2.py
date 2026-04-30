"""
Risk Engine - Advanced weighted scoring for authenticity risk assessment.

Improvements over original:
- Weighted multi-component scoring model
- Per-signal explanations
- Confidence calibration
- Threshold-based risk level mapping
- Mathematical transparency in risk calculation
"""

import time
from typing import Dict, List, Optional

from pipeline_schemas import (
    FusionEngineOutput,
    ValidationEngineOutput,
    ClassifierEngineOutput,
    RiskLevel,
    ConfidenceLevel,
    RiskSignal,
    RiskExplanationItem,
    RiskEngineOutput,
)


class RiskEngine:
    """Advanced risk scoring with weighted components."""

    def __init__(self):
        """Initialize risk engine with weights and thresholds."""
        # Component weights (must sum to 1.0)
        self.weights = {
            "consistency": 0.30,  # Multi-image agreement on critical fields
            "validation": 0.25,  # Data validation results
            "ocr_reliability": 0.20,  # OCR confidence and quality
            "classifier_anomaly": 0.15,  # Packaging form anomaly detection
            "field_completeness": 0.10,  # How many required fields are present
        }

        # Risk thresholds
        self.thresholds = {
            "low_upper": 34,
            "medium_upper": 64,
            "high_lower": 65,
        }

        # Penalty/boost values
        self.penalties = {
            "missing_batch": -20,
            "missing_expiry": -20,
            "missing_mfg": -10,
            "product_expired": -30,
            "invalid_dates": -15,
            "low_ocr_confidence": -10,
            "field_conflicts": -15,
            "unusual_classifier": -20,
        }

    def calculate_risk(
        self,
        fusion_output: FusionEngineOutput,
        validation_output: ValidationEngineOutput,
        classifier_output: ClassifierEngineOutput,
        num_images: int = 1,
    ) -> RiskEngineOutput:
        """Calculate comprehensive risk score."""
        start_time = time.time()

        # Calculate individual signals
        signal_components = []

        # Signal 1: Consistency Score
        consistency_signal = self._compute_consistency_signal(fusion_output)
        signal_components.append(consistency_signal)

        # Signal 2: Validation Score
        validation_signal = self._compute_validation_signal(validation_output)
        signal_components.append(validation_signal)

        # Signal 3: OCR Reliability
        ocr_signal = self._compute_ocr_signal(fusion_output, validation_output)
        signal_components.append(ocr_signal)

        # Signal 4: Classifier Anomaly
        classifier_signal = self._compute_classifier_signal(classifier_output)
        signal_components.append(classifier_signal)

        # Signal 5: Field Completeness
        completeness_signal = self._compute_completeness_signal(fusion_output)
        signal_components.append(completeness_signal)

        # Compute weighted risk score
        risk_score_float = self._compute_weighted_score(signal_components, self.weights)

        # Generate explanations
        explanations = self._generate_explanations(
            fusion_output, validation_output, classifier_output, signal_components
        )

        # Determine risk level
        risk_level = self._map_risk_level(risk_score_float)

        # Determine confidence level
        confidence_level = self._compute_confidence_level(fusion_output, num_images, len(explanations))

        # Convert to 0-100 scale
        risk_score = int(risk_score_float * 100)

        processing_time = time.time() - start_time

        return RiskEngineOutput(
            risk_score=risk_score,
            risk_level=risk_level,
            confidence_level=confidence_level,
            explanation=explanations,
            signal_components=signal_components,
            thresholds_used=self.thresholds,
            processing_time_seconds=processing_time,
        )

    # ========================================================================
    # SIGNAL COMPUTATION FUNCTIONS
    # ========================================================================

    def _compute_consistency_signal(self, fusion_output: FusionEngineOutput) -> RiskSignal:
        """Compute consistency signal (multi-image agreement on critical fields)."""
        # Higher consistency = lower risk
        raw_value = fusion_output.consistency_score  # 0.0-1.0

        weighted_value = raw_value

        return RiskSignal(
            name="consistency",
            raw_value=raw_value,
            weighted_value=weighted_value,
            weight=self.weights["consistency"],
            explanation=f"Multi-image agreement on critical fields: {raw_value:.0%}. "
            f"Higher agreement = lower risk.",
        )

    def _compute_validation_signal(self, validation_output: ValidationEngineOutput) -> RiskSignal:
        """Compute validation signal (data quality and rule compliance)."""
        # Start with data quality score
        base_value = validation_output.data_quality_score

        # Penalize errors
        error_count = sum(1 for issue in validation_output.issues if issue.severity == "ERROR")
        base_value -= error_count * 0.2

        # Clamp to [0, 1]
        raw_value = max(0.0, min(1.0, base_value))
        weighted_value = raw_value

        error_desc = f" ({error_count} errors)" if error_count > 0 else ""
        return RiskSignal(
            name="validation",
            raw_value=raw_value,
            weighted_value=weighted_value,
            weight=self.weights["validation"],
            explanation=f"Data validation quality: {raw_value:.0%}{error_desc}. "
            f"Failed validations increase risk.",
        )

    def _compute_ocr_signal(
        self, fusion_output: FusionEngineOutput, validation_output: ValidationEngineOutput
    ) -> RiskSignal:
        """Compute OCR reliability signal."""
        # Base on overall field confidence
        base_confidence = fusion_output.overall_field_confidence

        # Apply soft-knee penalty for low confidence
        if base_confidence < 0.3:
            # Aggressive penalty below 30%
            raw_value = 0.3 * (base_confidence / 0.3)
        else:
            # Linear above 30%
            raw_value = base_confidence

        raw_value = max(0.0, min(1.0, raw_value))
        weighted_value = raw_value

        return RiskSignal(
            name="ocr_reliability",
            raw_value=raw_value,
            weighted_value=weighted_value,
            weight=self.weights["ocr_reliability"],
            explanation=f"OCR field confidence: {raw_value:.0%}. "
            f"Low confidence increases risk.",
        )

    def _compute_classifier_signal(self, classifier_output: ClassifierEngineOutput) -> RiskSignal:
        """Compute classifier anomaly signal."""
        # Check if classifier detected unusual form
        from pipeline_schemas import PackagingForm

        # Assume certain forms are common (tablet, capsule, etc.)
        common_forms = {PackagingForm.TABLET, PackagingForm.CAPSULE, PackagingForm.SYRUP}

        if classifier_output.final_form in common_forms:
            # Common form = lower risk
            raw_value = 1.0  # Good signal
        elif classifier_output.final_form == PackagingForm.UNKNOWN:
            # Unknown = higher risk
            raw_value = 0.5
        else:
            # Unusual but known form
            raw_value = 0.7

        # Moderate by confidence
        raw_value = raw_value * classifier_output.confidence

        raw_value = max(0.0, min(1.0, raw_value))
        weighted_value = raw_value

        form_name = classifier_output.final_form.value
        return RiskSignal(
            name="classifier_anomaly",
            raw_value=raw_value,
            weighted_value=weighted_value,
            weight=self.weights["classifier_anomaly"],
            explanation=f"Packaging form: {form_name} (confidence: {classifier_output.confidence:.0%}). "
            f"Unusual forms increase risk.",
        )

    def _compute_completeness_signal(self, fusion_output: FusionEngineOutput) -> RiskSignal:
        """Compute field completeness signal."""
        # Count present fields
        fields_present = sum(
            1
            for field in [
                fusion_output.batch_number,
                fusion_output.expiry_date,
                fusion_output.mfg_date,
                fusion_output.medicine_name,
                fusion_output.manufacturer,
            ]
            if field.final_value is not None
        )

        # Out of 5 total fields (batch and expiry are critical)
        raw_value = fields_present / 5.0

        # Extra boost if critical fields present
        critical_present = (
            (1 if fusion_output.batch_number.final_value else 0)
            + (1 if fusion_output.expiry_date.final_value else 0)
        )
        if critical_present == 2:
            raw_value = min(1.0, raw_value + 0.2)

        raw_value = max(0.0, min(1.0, raw_value))
        weighted_value = raw_value

        return RiskSignal(
            name="field_completeness",
            raw_value=raw_value,
            weighted_value=weighted_value,
            weight=self.weights["field_completeness"],
            explanation=f"Field completeness: {fields_present}/5 fields present. "
            f"Missing critical fields increase risk.",
        )

    # ========================================================================
    # SCORE COMPUTATION & MAPPING
    # ========================================================================

    def _compute_weighted_score(self, signals: List[RiskSignal], weights: Dict[str, float]) -> float:
        """Compute weighted risk score from signals."""
        total = 0.0
        for signal in signals:
            # Invert for risk (high quality = low risk)
            risk_component = (1.0 - signal.weighted_value) * signal.weight
            total += risk_component

        # Clamp to [0, 1]
        return max(0.0, min(1.0, total))

    def _map_risk_level(self, risk_score_float: float) -> RiskLevel:
        """Map risk score to risk level."""
        risk_score = int(risk_score_float * 100)

        if risk_score <= self.thresholds["low_upper"]:
            return RiskLevel.LOW
        elif risk_score <= self.thresholds["medium_upper"]:
            return RiskLevel.MEDIUM
        else:
            return RiskLevel.HIGH

    # ========================================================================
    # EXPLANATION GENERATION
    # ========================================================================

    def _generate_explanations(
        self,
        fusion_output: FusionEngineOutput,
        validation_output: ValidationEngineOutput,
        classifier_output: ClassifierEngineOutput,
        signals: List[RiskSignal],
    ) -> List[RiskExplanationItem]:
        """Generate detailed risk explanations."""
        explanations = []

        # Check for missing critical fields
        if not fusion_output.batch_number.final_value:
            explanations.append(
                RiskExplanationItem(
                    reason="Missing batch number",
                    penalty_or_boost=-20,
                    severity="CRITICAL",
                )
            )

        if not fusion_output.expiry_date.final_value:
            explanations.append(
                RiskExplanationItem(
                    reason="Missing expiry date",
                    penalty_or_boost=-20,
                    severity="CRITICAL",
                )
            )

        # Check validation errors
        for issue in validation_output.issues:
            if issue.severity == "ERROR":
                penalty = -15 if issue.rule_violated == "PRODUCT_EXPIRED" else -10
                explanations.append(
                    RiskExplanationItem(
                        reason=issue.message,
                        penalty_or_boost=penalty,
                        severity="CRITICAL" if penalty <= -15 else "MAJOR",
                    )
                )

        # Check for field conflicts
        if fusion_output.conflicts_detected:
            explanations.append(
                RiskExplanationItem(
                    reason=f"Field conflicts in {len(fusion_output.conflicts_detected)} field(s)",
                    penalty_or_boost=-15,
                    severity="MAJOR",
                )
            )

        # Check OCR confidence
        if fusion_output.overall_field_confidence < 0.5:
            explanations.append(
                RiskExplanationItem(
                    reason="Low OCR confidence in extracted fields",
                    penalty_or_boost=-10,
                    severity="MAJOR",
                )
            )

        # Classifier anomaly
        from pipeline_schemas import PackagingForm

        if classifier_output.final_form == PackagingForm.UNKNOWN:
            explanations.append(
                RiskExplanationItem(
                    reason="Classifier could not determine packaging form",
                    penalty_or_boost=-10,
                    severity="MAJOR",
                )
            )

        # Sort by severity
        severity_order = {"CRITICAL": 0, "MAJOR": 1, "MINOR": 2}
        explanations.sort(key=lambda x: severity_order.get(x.severity, 3))

        return explanations

    def _compute_confidence_level(
        self, fusion_output: FusionEngineOutput, num_images: int, num_issues: int
    ) -> ConfidenceLevel:
        """Determine confidence level in risk assessment."""
        # Multi-image = higher confidence
        if num_images >= 2:
            base_confidence = 0.7
        else:
            base_confidence = 0.5

        # Consistency improves confidence
        base_confidence += fusion_output.consistency_score * 0.2

        # Issues reduce confidence
        base_confidence -= num_issues * 0.05

        # Clamp and map
        base_confidence = max(0.0, min(1.0, base_confidence))

        if base_confidence >= 0.7:
            return ConfidenceLevel.HIGH
        elif base_confidence >= 0.4:
            return ConfidenceLevel.MEDIUM
        else:
            return ConfidenceLevel.LOW
