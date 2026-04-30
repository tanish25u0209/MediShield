import time

# Read the full file with UTF-8 encoding
with open('medishield_ocr.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Append the new function
new_function = '''


# ============================================================================
# OCR CONTRACT GATEWAY - ORCHESTRATOR INTERFACE
# ============================================================================
# This function bridges the deterministic ocr_core() contract with the
# pipeline orchestrator's expected OCREngineOutput format.
#
# CRITICAL: Uses ONLY ocr_core() for Tesseract calls (2 per image).
# NO OCREngine calls. NO additional pytesseract invocations.
#
# ============================================================================

def process_medicine_images_with_ocr_core(image_paths):
    """
    Process medicine images using deterministic ocr_core() gateway.
    
    CONTRACT:
    - Exactly 2 pytesseract calls per image (enforced by ocr_core)
    - Returns OCREngineOutput compatible with pipeline orchestrator
    - No hidden OCR routing or fallback paths
    """
    from pipeline_schemas import OCREngineOutput, OCRImageResult, OCRFieldDetection
    
    image_results = []
    combined_raw_text = []
    start_time = time.time()
    
    for image_path in image_paths:
        try:
            # Use ocr_core() as single deterministic OCR gate (2 calls per image)
            raw_text, avg_confidence = ocr_core(image_path)
            combined_raw_text.append(raw_text)
            
            # Extract fields from raw text using legacy helpers
            medicine_name = _extract_strict_medicine_name(raw_text) or ""
            batch_number = _extract_strict_batch(raw_text) or ""
            expiry_date = _extract_strict_expiry(raw_text) or ""
            mfg_date = _extract_strict_mfg(raw_text) or ""
            manufacturer = _extract_strict_manufacturer(raw_text) or ""
            
            # Create per-field detection objects
            result = OCRImageResult(
                image_path=image_path,
                medicine_name=OCRFieldDetection(
                    value=medicine_name if medicine_name else None,
                    confidence=avg_confidence if medicine_name else 0.0,
                    raw_value=medicine_name or None,
                ),
                batch_number=OCRFieldDetection(
                    value=batch_number if batch_number else None,
                    confidence=avg_confidence if batch_number else 0.0,
                    raw_value=batch_number or None,
                ),
                expiry_date=OCRFieldDetection(
                    value=expiry_date if expiry_date else None,
                    confidence=avg_confidence if expiry_date else 0.0,
                    raw_value=expiry_date or None,
                ),
                mfg_date=OCRFieldDetection(
                    value=mfg_date if mfg_date else None,
                    confidence=avg_confidence if mfg_date else 0.0,
                    raw_value=mfg_date or None,
                ),
                manufacturer=OCRFieldDetection(
                    value=manufacturer if manufacturer else None,
                    confidence=avg_confidence if manufacturer else 0.0,
                    raw_value=manufacturer or None,
                ),
                raw_text=raw_text,
                overall_confidence=avg_confidence,
            )
            image_results.append(result)
            
        except Exception as exc:
            logger.warning(f"Error processing {image_path}: {exc}")
            image_results.append(
                OCRImageResult(
                    image_path=image_path,
                    medicine_name=OCRFieldDetection(value=None, confidence=0.0, raw_value=None),
                    batch_number=OCRFieldDetection(value=None, confidence=0.0, raw_value=None),
                    expiry_date=OCRFieldDetection(value=None, confidence=0.0, raw_value=None),
                    mfg_date=OCRFieldDetection(value=None, confidence=0.0, raw_value=None),
                    manufacturer=OCRFieldDetection(value=None, confidence=0.0, raw_value=None),
                    raw_text="",
                    overall_confidence=0.0,
                )
            )
    
    processing_time = time.time() - start_time
    
    return OCREngineOutput(
        image_results=image_results,
        raw_combined_text="\\n".join(combined_raw_text),
        processing_time_seconds=processing_time,
        notes=["OCR_CORE_CONTRACT: 2_tesseract_calls_per_image"],
    )
'''

# Write updated content
with open('medishield_ocr.py', 'w', encoding='utf-8') as f:
    f.write(content + new_function)

print("OCR gateway function appended successfully")
