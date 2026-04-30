"""
Fusion Engine - Multi-image field agreement with weighted consensus.

Improvements over original:
- Weighted agreement instead of simple voting
- Per-field confidence tracking through fusion
- Conflict detection and resolution
- Consistency scoring for critical fields
- Mathematical transparency in fusion decisions
"""

import time
from typing import Dict, List, Tuple, Optional
from collections import defaultdict

from pipeline_schemas import (
    OCREngineOutput,
    FieldFusion,
    FusionConflict,
    FusionEngineOutput,
    OCRFieldDetection,
)


class FusionEngine:
    """Multi-image fusion with weighted agreement system."""

    def __init__(self):
        """Initialize fusion engine with field weightings."""
        # Field importance weights (for consistency scoring)
        self.critical_fields = {"batch_number", "expiry_date"}
        self.important_fields = {"mfg_date"}
        self.minor_fields = {"medicine_name", "manufacturer"}

        # Weight multipliers for conflict detection
        self.critical_weight = 1.0
        self.important_weight = 0.6
        self.minor_weight = 0.3

    def fuse_results(self, ocr_output: OCREngineOutput) -> FusionEngineOutput:
        """Fuse OCR results across multiple images."""
        start_time = time.time()

        # Extract per-field results with confidences
        field_results = self._collect_field_results(ocr_output)

        # Perform weighted fusion per field
        fusions = {}
        conflicts = []

        for field_name in ["medicine_name", "batch_number", "expiry_date", "mfg_date", "manufacturer"]:
            fusion, conflict = self._fuse_field(field_name, field_results[field_name])
            fusions[field_name] = fusion

            if conflict:
                conflicts.append(conflict)

        # Compute consistency scores
        consistency_score = self._compute_consistency_score(fusions)

        # Compute overall field confidence
        overall_field_confidence = self._compute_overall_confidence(fusions)

        processing_time = time.time() - start_time

        return FusionEngineOutput(
            medicine_name=fusions["medicine_name"],
            batch_number=fusions["batch_number"],
            expiry_date=fusions["expiry_date"],
            mfg_date=fusions["mfg_date"],
            manufacturer=fusions["manufacturer"],
            overall_field_confidence=overall_field_confidence,
            conflicts_detected=conflicts,
            consistency_score=consistency_score,
            processing_time_seconds=processing_time,
        )

    def _collect_field_results(self, ocr_output: OCREngineOutput) -> Dict[str, List[Tuple[str, float]]]:
        """Collect all field values and confidences from OCR results."""
        collected = defaultdict(list)

        for image_result in ocr_output.image_results:
            fields = {
                "medicine_name": image_result.medicine_name,
                "batch_number": image_result.batch_number,
                "expiry_date": image_result.expiry_date,
                "mfg_date": image_result.mfg_date,
                "manufacturer": image_result.manufacturer,
            }

            for field_name, detection in fields.items():
                if detection.value is not None:
                    collected[field_name].append((detection.value, detection.confidence))

        return collected

    def _fuse_field(self, field_name: str, values_and_confs: List[Tuple[str, float]]) -> Tuple[FieldFusion, Optional[FusionConflict]]:
        """Fuse a single field across images using weighted agreement."""
        if not values_and_confs:
            # No data for this field
            return (
                FieldFusion(
                    final_value=None,
                    confidence=0.0,
                    agreement_score=0.0,
                    weighted_score=0.0,
                ),
                None,
            )

        if len(values_and_confs) == 1:
            # Single image - use its confidence
            value, conf = values_and_confs[0]
            return (
                FieldFusion(
                    final_value=value,
                    confidence=conf,
                    agreement_score=1.0,
                    weighted_score=conf,
                    is_confident=True,
                ),
                None,
            )

        # Multiple images - perform weighted voting
        vote_tally = defaultdict(float)
        total_weight = 0.0
        conflicting_values = {}

        for value, conf in values_and_confs:
            vote_tally[value] += conf
            total_weight += conf

        # Normalize votes
        normalized_votes = {v: s / total_weight for v, s in vote_tally.items()}

        # Find winner (highest weighted vote)
        winning_value = max(normalized_votes.keys(), key=lambda k: normalized_votes[k])
        winning_score = normalized_votes[winning_value]

        # Compute agreement score
        agreement_count = sum(1 for v, _ in values_and_confs if v == winning_value)
        agreement_score = agreement_count / len(values_and_confs)

        # Check for conflicts
        conflict = None
        if len(vote_tally) > 1:
            # Conflict detected - multiple distinct values
            conflicting_values = {v: vote for v, vote in normalized_votes.items() if v != winning_value}

            # Only mark as conflict if confidence gap is large
            second_best_score = max(
                (s for v, s in normalized_votes.items() if v != winning_value), default=0.0
            )

            if (winning_score - second_best_score) > 0.15 or agreement_score >= 0.6:
                # High confidence in winner - soft conflict
                conflict = FusionConflict(
                    field_name=field_name,
                    conflicting_values=list(vote_tally.keys()),
                    confidence_per_variant=normalized_votes,
                    resolution=f"Resolved to '{winning_value}' (weight: {winning_score:.2f}), "
                    f"agreement: {agreement_score:.0%}",
                )

        # Compute confidence considering agreement
        # High agreement = high confidence, even if individual OCR confidence is low
        fusion_confidence = (0.6 * agreement_score) + (0.4 * winning_score)

        is_confident = agreement_score >= 0.6 or (len(values_and_confs) == 1)

        return (
            FieldFusion(
                final_value=winning_value,
                confidence=fusion_confidence,
                agreement_score=agreement_score,
                weighted_score=winning_score,
                conflicting_values=conflicting_values,
                is_confident=is_confident,
            ),
            conflict,
        )

    def _compute_consistency_score(self, fusions: Dict[str, FieldFusion]) -> float:
        """
        Compute consistency score based on agreement on critical fields.

        High score = images agree on what matters most.
        """
        consistency_penalties = 0.0

        # Critical fields: batch_number, expiry_date
        for field_name in self.critical_fields:
            fusion = fusions[field_name]
            if not fusion.is_confident:
                consistency_penalties += 0.5 * self.critical_weight

        # Important fields: mfg_date
        for field_name in self.important_fields:
            fusion = fusions[field_name]
            if not fusion.is_confident:
                consistency_penalties += 0.3 * self.important_weight

        # Clamp to [0, 1]
        consistency_score = max(0.0, 1.0 - consistency_penalties)
        return consistency_score

    def _compute_overall_confidence(self, fusions: Dict[str, FieldFusion]) -> float:
        """Compute overall field confidence across all fields."""
        # Weight critical fields more heavily
        weighted_conf = 0.0
        total_weight = 0.0

        for field_name, fusion in fusions.items():
            if field_name in self.critical_fields:
                weight = self.critical_weight
            elif field_name in self.important_fields:
                weight = self.important_weight
            else:
                weight = self.minor_weight

            weighted_conf += fusion.confidence * weight
            total_weight += weight

        overall = weighted_conf / total_weight if total_weight > 0 else 0.0
        return overall
