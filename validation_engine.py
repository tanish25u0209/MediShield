"""
Validation Engine - Data quality checks and completeness scoring.

Validates:
- Required fields present and non-empty
- Date format validity and logical consistency
- Field value ranges and patterns
- Expiry status
- Data completeness and quality metrics
"""

import re
import time
from datetime import datetime
from typing import Dict, Optional, List

from pipeline_schemas import (
    FusionEngineOutput,
    ValidationIssue,
    ValidationEngineOutput,
)


class ValidationEngine:
    """Data validation and quality scoring."""

    def __init__(self):
        """Initialize validation engine with rules."""
        self.required_fields = ["batch_number", "expiry_date"]
        self.important_fields = ["mfg_date", "medicine_name"]
        self.total_fields = 5  # batch, expiry, mfg, name, manufacturer

    def validate(self, fusion_output: FusionEngineOutput) -> ValidationEngineOutput:
        """Validate fused data."""
        start_time = time.time()
        issues = []

        # Extract final data
        final_data = {
            "medicine_name": fusion_output.medicine_name.final_value,
            "batch_number": fusion_output.batch_number.final_value,
            "expiry_date": fusion_output.expiry_date.final_value,
            "mfg_date": fusion_output.mfg_date.final_value,
            "manufacturer": fusion_output.manufacturer.final_value,
        }

        # Rule 1: Check required fields
        for field_name in self.required_fields:
            if not final_data[field_name]:
                issues.append(
                    ValidationIssue(
                        field=field_name,
                        severity="ERROR",
                        message=f"Required field '{field_name}' is missing",
                        rule_violated="REQUIRED_FIELD_MISSING",
                    )
                )

        # Rule 2: Check important fields
        for field_name in self.important_fields:
            if not final_data[field_name]:
                issues.append(
                    ValidationIssue(
                        field=field_name,
                        severity="WARNING",
                        message=f"Important field '{field_name}' is missing",
                        rule_violated="IMPORTANT_FIELD_MISSING",
                    )
                )

        # Rule 3: Validate date formats
        if final_data["expiry_date"]:
            if not self._is_valid_date_format(final_data["expiry_date"]):
                issues.append(
                    ValidationIssue(
                        field="expiry_date",
                        severity="ERROR",
                        message=f"Invalid expiry date format: {final_data['expiry_date']}. Expected MM/YYYY.",
                        rule_violated="INVALID_DATE_FORMAT",
                    )
                )
            else:
                # Check if expired
                if self._is_expired(final_data["expiry_date"]):
                    issues.append(
                        ValidationIssue(
                            field="expiry_date",
                            severity="ERROR",
                            message=f"Product has expired (expiry: {final_data['expiry_date']})",
                            rule_violated="PRODUCT_EXPIRED",
                        )
                    )

        if final_data["mfg_date"]:
            if not self._is_valid_date_format(final_data["mfg_date"]):
                issues.append(
                    ValidationIssue(
                        field="mfg_date",
                        severity="WARNING",
                        message=f"Invalid manufacturing date format: {final_data['mfg_date']}. Expected MM/YYYY.",
                        rule_violated="INVALID_DATE_FORMAT",
                    )
                )

        # Rule 4: Check date logic (mfg before expiry)
        if final_data["mfg_date"] and final_data["expiry_date"]:
            if not self._validate_date_order(final_data["mfg_date"], final_data["expiry_date"]):
                issues.append(
                    ValidationIssue(
                        field="mfg_date",
                        severity="WARNING",
                        message=f"Manufacturing date ({final_data['mfg_date']}) is after expiry date ({final_data['expiry_date']})",
                        rule_violated="INVALID_DATE_ORDER",
                    )
                )

        # Rule 5: Check batch number format
        if final_data["batch_number"]:
            if not self._is_valid_batch_format(final_data["batch_number"]):
                issues.append(
                    ValidationIssue(
                        field="batch_number",
                        severity="WARNING",
                        message=f"Batch number format looks unusual: {final_data['batch_number']}",
                        rule_violated="UNUSUAL_BATCH_FORMAT",
                    )
                )

        # Rule 6: Check medicine name length
        if final_data["medicine_name"]:
            if len(final_data["medicine_name"]) < 3:
                issues.append(
                    ValidationIssue(
                        field="medicine_name",
                        severity="WARNING",
                        message=f"Medicine name is very short: {final_data['medicine_name']}",
                        rule_violated="SHORT_MEDICINE_NAME",
                    )
                )

        # Compute quality metrics
        completeness_score = self._compute_completeness(final_data)
        data_quality_score = self._compute_data_quality(final_data, issues)

        # Is valid = no errors (warnings are OK)
        is_valid = not any(issue.severity == "ERROR" for issue in issues)

        processing_time = time.time() - start_time

        return ValidationEngineOutput(
            is_valid=is_valid,
            issues=issues,
            completeness_score=completeness_score,
            data_quality_score=data_quality_score,
            processing_time_seconds=processing_time,
        )

    def _is_valid_date_format(self, date_str: str) -> bool:
        """Check if date is in MM/YYYY format."""
        return bool(re.match(r"^\d{2}/\d{4}$", str(date_str)))

    def _is_expired(self, expiry_date: str) -> bool:
        """Check if product has expired."""
        try:
            parts = expiry_date.split("/")
            month = int(parts[0])
            year = int(parts[1])

            # Create date at end of expiry month
            expiry = datetime(year, month, 1)

            # Move to next month first, then move back to last day
            if month == 12:
                next_month = datetime(year + 1, 1, 1)
            else:
                next_month = datetime(year, month + 1, 1)

            # Check if today is past end of month
            today = datetime.now()
            return today > next_month

        except Exception:
            return False

    def _validate_date_order(self, mfg_date: str, expiry_date: str) -> bool:
        """Check that manufacturing date is before expiry date."""
        try:
            mfg_parts = mfg_date.split("/")
            exp_parts = expiry_date.split("/")

            mfg_year = int(mfg_parts[1])
            mfg_month = int(mfg_parts[0])

            exp_year = int(exp_parts[1])
            exp_month = int(exp_parts[0])

            # Compare year-month tuples
            mfg_tuple = (mfg_year, mfg_month)
            exp_tuple = (exp_year, exp_month)

            return mfg_tuple < exp_tuple

        except Exception:
            return True  # If parsing fails, assume valid

    def _is_valid_batch_format(self, batch: str) -> bool:
        """Check if batch number looks valid."""
        # Valid formats: alphanumeric, 2-8 characters
        return bool(re.match(r"^[A-Z0-9]{2,8}$", batch.upper()))

    def _compute_completeness(self, final_data: Dict[str, Optional[str]]) -> float:
        """Compute field completeness score."""
        fields_present = sum(1 for v in final_data.values() if v is not None)
        return fields_present / self.total_fields

    def _compute_data_quality(self, final_data: Dict[str, Optional[str]], issues: List[ValidationIssue]) -> float:
        """Compute overall data quality score."""
        base_score = 1.0

        # Deduct for missing critical fields
        if not final_data["batch_number"]:
            base_score -= 0.3
        if not final_data["expiry_date"]:
            base_score -= 0.3

        # Deduct for missing important fields
        if not final_data["mfg_date"]:
            base_score -= 0.1
        if not final_data["medicine_name"]:
            base_score -= 0.1

        # Deduct for errors
        for issue in issues:
            if issue.severity == "ERROR":
                base_score -= 0.2
            elif issue.severity == "WARNING":
                base_score -= 0.05

        return max(0.0, base_score)
