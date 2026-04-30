"""
OCR Diagnostic: Understanding why extraction is failing

This script analyzes:
1. What raw text Tesseract is extracting
2. What regions are being detected
3. Why pattern matching is failing
4. What the real bottleneck is
"""

from pathlib import Path
import cv2
import numpy as np

print("\n" + "="*90)
print("  OCR DIAGNOSTIC: Understanding Extraction Failures")
print("="*90 + "\n")

from medishield_ocr import (
    preprocess_image, extract_text, _load_image_bgr,
    detect_text_regions, crop_region_for_medicine_name,
    crop_region_for_batch_expiry, extract_text_from_region
)

# Analyze first sample
sample_dir = Path("samples/001")
images = sorted(sample_dir.glob("*.jpg")) + sorted(sample_dir.glob("*.png"))

if not images:
    print("✗ No images found in samples/001")
    exit(1)

print(f"Analyzing {len(images)} image(s) from {sample_dir.name}\n")

for img_idx, img_path in enumerate(images, 1):
    print(f"{'='*90}")
    print(f"IMAGE {img_idx}: {img_path.name}")
    print(f"{'='*90}\n")
    
    # Get file info
    file_size_kb = img_path.stat().st_size / 1024
    print(f"File size: {file_size_kb:.1f} KB")
    
    # Load image
    try:
        img_bgr = _load_image_bgr(str(img_path))
        h, w = img_bgr.shape[:2]
        print(f"Dimensions: {w}x{h}\n")
        
        # Stage 1: Preprocessing
        print("STAGE 1: PREPROCESSING")
        print("-" * 90)
        preprocessed = preprocess_image(img_bgr)
        print(f"  Preprocessed shape: {preprocessed.shape}")
        print(f"  Non-zero pixels: {np.count_nonzero(preprocessed)} / {preprocessed.size}")
        
        # Stage 2: Full-image OCR
        print("\nSTAGE 2: FULL-IMAGE OCR")
        print("-" * 90)
        raw_text = extract_text(preprocessed)
        print(f"  Raw OCR text length: {len(raw_text)} chars")
        if raw_text:
            print(f"  First 100 chars: {raw_text[:100]!r}")
            print(f"  Full text:\n    {repr(raw_text)}")
        else:
            print("  ✗ No text extracted!")
        
        # Stage 3: Region detection
        print("\nSTAGE 3: REGION DETECTION")
        print("-" * 90)
        
        # Create binary for region detection
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        binary = cv2.adaptiveThreshold(
            blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, 2
        )
        
        regions = detect_text_regions(binary)
        print(f"  Regions detected: {len(regions)}")
        for r_idx, r in enumerate(regions, 1):
            print(f"    Region {r_idx}: ({r['x_min']}, {r['y_min']}) to ({r['x_max']}, {r['y_max']}) " +
                  f"area={r['area']} density={r['density']:.3f}")
        
        # Stage 4: Crop regions
        print("\nSTAGE 4: REGION EXTRACTION")
        print("-" * 90)
        
        name_region = crop_region_for_medicine_name(img_bgr, binary)
        if name_region is not None:
            print(f"  Name region found: {name_region.shape}")
            name_text = extract_text_from_region(name_region, target_field='name')
            print(f"  Name region OCR: {name_text!r}")
        else:
            print(f"  ✗ No name region found")
        
        batch_region = crop_region_for_batch_expiry(img_bgr, binary)
        if batch_region is not None:
            print(f"  Batch region found: {batch_region.shape}")
            batch_text = extract_text_from_region(batch_region, target_field='batch')
            print(f"  Batch region OCR: {batch_text!r}")
        else:
            print(f"  ✗ No batch region found")
        
        print()
        
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()

print("="*90 + "\n")
