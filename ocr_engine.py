"""
OCR Engine - Advanced text extraction with per-field confidence scoring.

Improvements over original:
- Adaptive preprocessing based on image characteristics
- Per-field confidence scoring (not global)
- Region-based fallback with reliability weighting
- Enhanced regex patterns with stricter validation
- Detailed preprocessing logs for debugging
"""

import cv2
import numpy as np
import pytesseract
import re
from pathlib import Path
from typing import Optional, Dict, Tuple, List
import time

from pipeline_schemas import (
    OCRFieldDetection,
    OCRImageResult,
    OCREngineOutput,
)


class OCREngine:
    """Advanced OCR extraction engine with adaptive preprocessing."""

    def __init__(self):
        """Initialize OCR engine with field patterns and preprocessing configs."""
        self.psm_configs = {
            6: "--psm 6",  # Assume single block of text
            11: "--psm 11",  # Sparse text
            4: "--psm 4",  # Single column
        }

        # Enhanced regex patterns with stricter validation
        self.patterns = {
            "batch_number": [
                r"(?:batch|lot|b\.?\s*|#\s*)(\d{2,6}(?:[A-Z]{1,3})?)",  # Batch LOT123ABC
                r"(?:lot\s*#?|batch\s*#?)(\d{2,6})",  # Lot #123 format
                r"^([0-9]{2,6}(?:[A-Z]{1,3})?)$",  # Standalone batch number
            ],
            "expiry_date": [
                r"(?:exp|expiry|valid until|exp\.\s*|exp\s*:?)\s*(\d{1,2})[/\-.](\d{4})",  # MM/YYYY or DD/YYYY
                r"(\d{1,2})[/\-.](\d{4})(?:\s*(?:exp|expiry|valid))?",  # YYYY/MM
            ],
            "mfg_date": [
                r"(?:mfg|manufactured|made|date|mfd|mfg\.?)[\s:]*(\d{1,2})[/\-.](\d{4})",  # MM/YYYY format
                r"(?:made in|manufactured)[\s:](\d{1,2})[/\-.](\d{4})",
            ],
            "medicine_name": [
                r"^([A-Za-z\s\-\(\)]+?)(?:\d+\s*(?:mg|ml|iu|%|mcg))?$",  # Medicine name with optional dose
            ],
            "manufacturer": [
                r"(?:mfg|manufactured by|manufacturer|made by)[\s:]+([A-Za-z0-9\s\&\.\,-]+?)(?:\d+|[A-Z]{2}|$)",
            ],
        }

        # Field weights for importance
        self.field_weights = {
            "batch_number": 0.4,
            "expiry_date": 0.3,
            "mfg_date": 0.15,
            "medicine_name": 0.1,
            "manufacturer": 0.05,
        }

    def process_image_file(self, image_path: str) -> OCRImageResult:
        """Process a single image file and extract text/fields."""
        start_time = time.time()

        try:
            # Load image
            img = cv2.imread(image_path)
            if img is None:
                raise IOError(f"Failed to load image: {image_path}")

            return self.process_image_array(img, image_path)
        except Exception as e:
            # Return minimal result on error
            return OCRImageResult(
                image_path=image_path,
                medicine_name=OCRFieldDetection(value=None, confidence=0.0, raw_value=None),
                batch_number=OCRFieldDetection(value=None, confidence=0.0, raw_value=None),
                expiry_date=OCRFieldDetection(value=None, confidence=0.0, raw_value=None),
                mfg_date=OCRFieldDetection(value=None, confidence=0.0, raw_value=None),
                manufacturer=OCRFieldDetection(value=None, confidence=0.0, raw_value=None),
                raw_text="",
                preprocessing_log={"error": str(e)},
            )

    def process_image_array(self, img: np.ndarray, image_path: str = "unknown") -> OCRImageResult:
        """Process image array and extract OCR data."""
        preprocessing_log: Dict[str, any] = {}

        # Stage 1: Adaptive Preprocessing
        img_work = self._adaptive_preprocess(img, preprocessing_log)

        # Stage 2: Multi-PSM OCR extraction
        raw_text = self._extract_text_multimodal(img_work, preprocessing_log)

        # Stage 3: Text normalization
        normalized_text = self._normalize_text(raw_text)

        # Stage 4: Field extraction with per-field confidence
        fields = self._extract_fields_with_confidence(normalized_text, raw_text)

        # Stage 5: Region-based fallback for low-confidence fields
        fields = self._apply_region_fallback(img, fields, preprocessing_log)

        # Stage 6: Compute overall OCR confidence
        overall_confidence = self._compute_overall_confidence(fields)

        return OCRImageResult(
            image_path=str(image_path),
            medicine_name=fields["medicine_name"],
            batch_number=fields["batch_number"],
            expiry_date=fields["expiry_date"],
            mfg_date=fields["mfg_date"],
            manufacturer=fields["manufacturer"],
            raw_text=raw_text,
            preprocessing_log=preprocessing_log,
            overall_confidence=overall_confidence,
        )

    def _adaptive_preprocess(self, img: np.ndarray, log: Dict) -> np.ndarray:
        """Adaptive preprocessing based on image characteristics."""
        h, w = img.shape[:2]

        # Step 1: Resize if needed (target 800px width for optimal Tesseract)
        if w < 400:
            scale = 800 / w
            img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            log["resize"] = f"Upscaled to {img.shape[1]}x{img.shape[0]}"
        elif w > 1200:
            scale = 800 / w
            img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            log["resize"] = f"Downscaled to {img.shape[1]}x{img.shape[0]}"

        # Step 2: Convert to grayscale
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img.copy()
        log["grayscale"] = "Applied"

        # Step 3: Analyze image characteristics for adaptive processing
        brightness = np.mean(gray)
        contrast = np.std(gray)
        log["image_stats"] = {"brightness": float(brightness), "contrast": float(contrast)}

        # Step 4: Adaptive contrast enhancement (CLAHE)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        log["contrast_enhancement"] = "CLAHE applied"

        # Step 5: Denoising
        denoised = cv2.fastNlMeansDenoising(enhanced, None, h=10, templateWindowSize=7, searchWindowSize=21)
        log["denoising"] = "fastNlMeansDenoising applied"

        # Step 6: Adaptive thresholding
        binary = cv2.adaptiveThreshold(
            denoised,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            blockSize=11,
            C=2,
        )
        log["thresholding"] = "Adaptive Gaussian threshold"

        # Step 7: Morphological cleanup (optional erosion/dilation)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 1))
        processed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)
        log["morphology"] = "Closing operation"

        return processed

    def _extract_text_multimodal(self, img: np.ndarray, log: Dict) -> str:
        """Extract text using multiple PSM configs and pick best."""
        results = {}

        for psm_val, psm_str in self.psm_configs.items():
            try:
                config = f"--oem 3 {psm_str}"
                text = pytesseract.image_to_string(img, config=config)
                confidence_data = pytesseract.image_to_data(img, config=config, output_type=pytesseract.Output.DICT)

                # Compute confidence for this extraction
                confs = [int(c) for c in confidence_data["conf"] if int(c) > 0]
                avg_conf = np.mean(confs) if confs else 0
                results[psm_val] = {
                    "text": text,
                    "confidence": avg_conf,
                    "words_detected": len([c for c in confidence_data["conf"] if int(c) > 0]),
                }
            except Exception as e:
                log[f"ocr_psm_{psm_val}_error"] = str(e)

        # Select PSM with highest confidence
        if results:
            best_psm = max(results.keys(), key=lambda k: results[k]["confidence"])
            best_text = results[best_psm]["text"]
            log["best_psm"] = best_psm
            log["psm_confidences"] = {str(k): v["confidence"] for k, v in results.items()}
        else:
            best_text = ""

        return best_text

    def _normalize_text(self, text: str) -> str:
        """Normalize extracted OCR text."""
        # Common OCR errors
        corrections = {
            r"\|": "I",  # Pipe to I
            r"0O": "OO",  # Common confusion
            r"l": "1",  # Lowercase l to 1 in numbers
            r"\s+": " ",  # Collapse whitespace
        }

        normalized = text.lower()
        for pattern, replacement in corrections.items():
            normalized = re.sub(pattern, replacement, normalized)

        return normalized

    def _extract_fields_with_confidence(
        self, normalized_text: str, raw_text: str
    ) -> Dict[str, OCRFieldDetection]:
        """Extract fields with per-field confidence scores."""
        fields = {}

        for field_name, patterns in self.patterns.items():
            best_match = None
            best_confidence = 0.0
            best_raw = None

            for pattern in patterns:
                try:
                    matches = re.finditer(pattern, normalized_text, re.IGNORECASE)
                    for match in matches:
                        extracted = match.group(1).strip()

                        # Compute confidence for this extraction
                        confidence = self._compute_field_confidence(field_name, extracted, len(matches))

                        if confidence > best_confidence:
                            best_confidence = confidence
                            best_match = extracted
                            best_raw = match.group(0)

                except Exception as e:
                    pass

            # Normalize extracted value
            normalized_value = None
            if best_match:
                normalized_value = self._normalize_field_value(field_name, best_match)

            fields[field_name] = OCRFieldDetection(
                value=normalized_value,
                confidence=best_confidence,
                raw_value=best_raw,
                regex_match=best_match is not None,
            )

        return fields

    def _compute_field_confidence(self, field_name: str, value: str, match_count: int) -> float:
        """Compute per-field confidence score."""
        base_confidence = 0.7  # Base from regex match

        # Length checks
        if field_name == "batch_number":
            if 2 <= len(value) <= 8:
                base_confidence += 0.2
        elif field_name == "expiry_date":
            if re.match(r"^\d{1,2}/\d{4}$", value):
                base_confidence += 0.2
        elif field_name == "medicine_name":
            if len(value) >= 3:
                base_confidence += 0.15

        # Penalize if multiple matches (uncertainty)
        if match_count > 1:
            base_confidence *= 0.9

        return min(base_confidence, 1.0)

    def _normalize_field_value(self, field_name: str, value: str) -> Optional[str]:
        """Normalize extracted field value."""
        value = value.strip()

        if field_name == "batch_number":
            # Uppercase batch numbers
            return value.upper()
        elif field_name == "expiry_date" or field_name == "mfg_date":
            # Standardize date format to MM/YYYY
            match = re.search(r"(\d{1,2})[/\-.](\d{4})", value)
            if match:
                month, year = match.groups()
                return f"{int(month):02d}/{year}"
            return None
        elif field_name == "medicine_name":
            # Title case for medicine names
            return " ".join(word.capitalize() for word in value.split())
        elif field_name == "manufacturer":
            return value.title()

        return value

    def _apply_region_fallback(
        self, img: np.ndarray, fields: Dict[str, OCRFieldDetection], log: Dict
    ) -> Dict[str, OCRFieldDetection]:
        """Apply region-based extraction fallback for low-confidence fields."""
        fallback_applied = []

        for field_name, detection in fields.items():
            if detection.confidence < 0.5:
                # Try region-based extraction
                regions = {
                    "batch_number": "top",
                    "expiry_date": "bottom",
                    "mfg_date": "bottom",
                }

                if field_name in regions:
                    region_img = self._extract_region(img, regions[field_name])
                    try:
                        region_text = pytesseract.image_to_string(region_img, config="--psm 6")
                        region_normalized = self._normalize_text(region_text)

                        # Try to match pattern in region
                        patterns = self.patterns.get(field_name, [])
                        for pattern in patterns:
                            match = re.search(pattern, region_normalized, re.IGNORECASE)
                            if match:
                                region_confidence = detection.confidence + 0.2
                                if region_confidence > detection.confidence:
                                    fields[field_name].confidence = region_confidence
                                    fields[field_name].region = regions[field_name]
                                    fallback_applied.append(field_name)
                    except:
                        pass

        if fallback_applied:
            log["region_fallback_applied"] = fallback_applied

        return fields

    def _extract_region(self, img: np.ndarray, region: str) -> np.ndarray:
        """Extract top/middle/bottom region from image."""
        h, w = img.shape[:2]

        if region == "top":
            return img[: h // 4, :]
        elif region == "bottom":
            return img[3 * h // 4 :, :]
        elif region == "middle":
            return img[h // 4 : 3 * h // 4, :]

        return img

    def _compute_overall_confidence(self, fields: Dict[str, OCRFieldDetection]) -> float:
        """Compute overall OCR confidence from per-field scores."""
        field_confs = [detection.confidence for detection in fields.values()]

        if not field_confs:
            return 0.0

        # Weighted average of field confidences
        weighted_sum = sum(
            detection.confidence * self.field_weights.get(name, 0.1)
            for name, detection in fields.items()
        )
        total_weight = sum(self.field_weights.values())

        return weighted_sum / total_weight

    def process_multiple_images(self, image_paths: List[str]) -> OCREngineOutput:
        """Process multiple images and combine results."""
        start_time = time.time()
        image_results = []

        for image_path in image_paths:
            result = self.process_image_file(image_path)
            image_results.append(result)

        # Combine raw text
        raw_combined = "\n---IMAGE BOUNDARY---\n".join(
            result.raw_text for result in image_results
        )

        processing_time = time.time() - start_time

        return OCREngineOutput(
            image_results=image_results,
            raw_combined_text=raw_combined,
            processing_time_seconds=processing_time,
        )
