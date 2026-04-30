#!/usr/bin/env python3
"""
MediShield Dataset Acquisition Tool (PHASE 1)

Attempts to acquire high-quality pharmaceutical images from multiple sources:
1. Kaggle datasets (if API configured)
2. E-commerce screenshots (if manual)
3. Synthetic generation (fallback)

Requirements:
- For Kaggle: pip install kaggle
- For synthetic: pip install pillow

Usage:
    python acquire_dataset.py --source kaggle        # Try Kaggle API
    python acquire_dataset.py --source synthetic     # Create fake data
    python acquire_dataset.py --help                 # Show options
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
import argparse

# Synthetic image generation (fallback)
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("⚠ PIL not installed. Install with: pip install pillow")

class DatasetAcquisition:
    def __init__(self, base_dir="medishield_data"):
        self.base_dir = Path(base_dir)
        self.raw_dir = self.base_dir / "raw"
        self.metadata_file = self.base_dir / "metadata.json"
        self.create_directories()
        
    def create_directories(self):
        """Create folder structure"""
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        print(f"✓ Created directories at {self.base_dir}")
    
    def try_kaggle_download(self):
        """Try downloading from Kaggle API"""
        print("\n" + "="*70)
        print("PHASE 1.1: Attempting Kaggle Dataset Download")
        print("="*70)
        
        try:
            # Check if kaggle is installed
            result = subprocess.run(
                ["kaggle", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                print("✗ Kaggle CLI not installed")
                print("  Install with: pip install kaggle")
                return False
            
            print(f"✓ Kaggle CLI found: {result.stdout.strip()}")
            
            # Try downloading a dataset
            datasets_to_try = [
                "imtkaggle/indian-medicines",
                "pzimmerman/amazon-fresh-medicines",
                "krishnaik06/pharma-supply-chain-dataset"
            ]
            
            for dataset in datasets_to_try:
                print(f"\n  Attempting: {dataset}")
                result = subprocess.run(
                    ["kaggle", "datasets", "download", dataset, "-p", str(self.raw_dir)],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                if result.returncode == 0:
                    print(f"  ✓ Downloaded {dataset}")
                    # Extract if zip
                    zip_files = list(self.raw_dir.glob("*.zip"))
                    for zf in zip_files:
                        print(f"  Extracting {zf.name}...")
                        subprocess.run(["powershell", "-Command", f"Expand-Archive -Path '{zf}' -DestinationPath '{self.raw_dir}'"], timeout=30)
                        zf.unlink()
                    return True
                else:
                    error = result.stderr.strip()
                    if "Unauthorized" in error or "401" in error:
                        print(f"  ✗ Not authenticated - Kaggle key missing/invalid")
                    elif "Not Found" in error:
                        print(f"  ✗ Dataset not found")
                    else:
                        print(f"  ✗ Error: {error[:100]}")
            
            return False
            
        except FileNotFoundError:
            print("✗ Kaggle CLI not found in PATH")
            print("  Install with: pip install kaggle")
            return False
        except subprocess.TimeoutExpired:
            print("✗ Kaggle command timeout")
            return False
        except Exception as e:
            print(f"✗ Kaggle download failed: {e}")
            return False
    
    def create_synthetic_dataset(self, num_samples=15):
        """Create synthetic pharmaceutical labels for testing"""
        print("\n" + "="*70)
        print(f"PHASE 1.2: Creating Synthetic Dataset ({num_samples} samples)")
        print("="*70)
        
        medicines = [
            ("Paracetamol 500mg Tablet", "BAT/2024/00145", "12/2026", "06/2024", "ABC Pharma Ltd"),
            ("Aspirin 100mg Tablet", "B20240515", "10/2026", "05/2024", "XYZ Medications"),
            ("Amoxicillin 500mg Capsule", "LOT-2024-0087", "08/2027", "02/2024", "Cipla Limited"),
            ("Ibuprofen 200mg Tablet", "BATCH-024-56", "09/2026", "03/2024", "Sun Pharma"),
            ("Metformin 500mg Tablet", "BAT/MET/2024/001", "11/2026", "05/2024", "Abbott India"),
            ("Cough Syrup 100ml", "SYRUP-2024-45", "06/2027", "01/2024", "Dr Reddy's"),
            ("Multivitamin Tablet", "MV-024-789", "07/2027", "04/2024", "Lupin Limited"),
            ("Vitamin C 500mg", "VIT-C-2024-56", "12/2026", "08/2024", "Glaxo Smithkline"),
            ("Antacid 250mg", "ANTACID-24-01", "09/2026", "06/2024", "Reckitt Benckiser"),
            ("Antihistamine Tablet", "AH-2024-0045", "10/2027", "02/2024", "Novartis India"),
            ("Probiotic Capsule", "PROB-024-123", "06/2027", "03/2024", "BioGain Labs"),
            ("Iron Supplement 65mg", "IR-2024-456", "08/2026", "07/2024", "SteriChem Pharma"),
            ("Calcium 600mg", "CAL-024-789", "11/2026", "05/2024", "WockHardt Limited"),
            ("Zinc 15mg Tablet", "ZINC-2024-012", "12/2026", "09/2024", "Mankind Pharma"),
            ("Omega-3 Fatty Acid", "OMEGA3-2024-99", "07/2027", "04/2024", "HealthCare Plus"),
        ]
        
        try:
            generated_count = 0
            for i, (name, batch, expiry, mfg, maker) in enumerate(medicines[:num_samples], 1):
                # Create folder for this medicine
                med_folder = self.raw_dir / f"synthetic_{i:02d}_{name.split()[0].lower()}"
                med_folder.mkdir(parents=True, exist_ok=True)
                
                # Generate front label image
                img = self._create_label_image(
                    medicine_name=name,
                    batch_number=batch,
                    expiry_date=expiry,
                    mfg_date=mfg,
                    manufacturer=maker,
                    label="FRONT"
                )
                front_path = med_folder / "front.jpg"
                img.save(front_path, quality=95)
                print(f"  ✓ Created {front_path.name}")
                
                # Generate back label image (batch/expiry emphasized)
                img = self._create_label_image(
                    medicine_name=name,
                    batch_number=batch,
                    expiry_date=expiry,
                    mfg_date=mfg,
                    manufacturer=maker,
                    label="BACK"
                )
                back_path = med_folder / "back.jpg"
                img.save(back_path, quality=95)
                print(f"  ✓ Created {back_path.name}")
                
                generated_count += 1
                
                # Save metadata
                if not self.metadata_file.exists():
                    self.metadata = {}
                else:
                    with open(self.metadata_file) as f:
                        self.metadata = json.load(f)
                
                self.metadata[f"synthetic_{i:02d}"] = {
                    "medicine_name": name,
                    "batch_number": batch,
                    "expiry_date": expiry,
                    "mfg_date": mfg,
                    "manufacturer": maker,
                    "source": "synthetic",
                    "created_at": datetime.now().isoformat()
                }
            
            with open(self.metadata_file, "w") as f:
                json.dump(self.metadata, f, indent=2)
            
            print(f"\n✓ Created {generated_count} synthetic samples")
            print(f"✓ Metadata saved to {self.metadata_file}")
            return True
            
        except Exception as e:
            print(f"✗ Synthetic generation failed: {e}")
            return False
    
    def _create_label_image(self, medicine_name, batch_number, expiry_date, mfg_date, manufacturer, label="FRONT"):
        """Create a realistic medicine label image (PIL)"""
        width, height = 800, 800
        img = Image.new("RGB", (width, height), color=(245, 245, 245))
        draw = ImageDraw.Draw(img)
        
        # Try to use a nice font, fallback to default
        try:
            title_font = ImageFont.truetype("arial.ttf", 48)
            normal_font = ImageFont.truetype("arial.ttf", 32)
            small_font = ImageFont.truetype("arial.ttf", 24)
        except:
            title_font = ImageFont.load_default()
            normal_font = ImageFont.load_default()
            small_font = ImageFont.load_default()
        
        # Background color
        draw.rectangle([50, 50, 750, 750], fill=(255, 255, 255), outline=(0, 0, 0), width=3)
        
        if label == "FRONT":
            # Front label - emphasis on medicine name
            
            # Header box
            draw.rectangle([60, 60, 740, 150], fill=(25, 118, 210), outline=(0, 0, 0), width=2)
            draw.text((400, 100), "PHARMACEUTICAL", fill=(255, 255, 255), font=small_font, anchor="mm")
            
            # Medicine name (large, centered)
            draw.text((400, 300), medicine_name, fill=(0, 0, 0), font=title_font, anchor="mm")
            
            # Manufacturer
            draw.text((400, 450), f"Mfg: {manufacturer}", fill=(60, 60, 60), font=normal_font, anchor="mm")
            
            # Footer info
            draw.text((100, 650), f"Keep in cool, dry place", fill=(80, 80, 80), font=small_font, anchor="lm")
            draw.text((700, 650), f"WHO-GMP", fill=(80, 80, 80), font=small_font, anchor="rm")
            
        else:  # BACK
            # Back label - emphasis on batch/expiry
            
            # Title
            draw.text((400, 100), "BATCH & EXPIRY INFORMATION", fill=(0, 0, 0), font=normal_font, anchor="mm")
            draw.line([80, 140, 720, 140], fill=(200, 200, 200), width=2)
            
            # Batch info (large, readable)
            draw.text((100, 280), "Batch Number:", fill=(0, 0, 0), font=small_font, anchor="lm")
            draw.rectangle([100, 320, 700, 380], fill=(255, 255, 200), outline=(0, 0, 0), width=2)
            draw.text((400, 350), batch_number, fill=(0, 0, 0), font=title_font, anchor="mm")
            
            # Expiry info (critical)
            draw.text((100, 450), "Expiry Date:", fill=(200, 0, 0), font=small_font, anchor="lm")
            draw.rectangle([100, 490, 700, 550], fill=(255, 200, 200), outline=(200, 0, 0), width=3)
            draw.text((400, 520), f"{expiry_date}", fill=(200, 0, 0), font=title_font, anchor="mm")
            
            # Mfg date
            draw.text((100, 620), f"Manufactured: {mfg_date}", fill=(60, 60, 60), font=small_font, anchor="lm")
        
        return img
    
    def verify_dataset(self):
        """Check quality of acquired images"""
        print("\n" + "="*70)
        print("PHASE 1.3: Verifying Dataset Quality")
        print("="*70)
        
        image_dirs = list(self.raw_dir.glob("*/"))
        if not image_dirs:
            print("✗ No images found in", self.raw_dir)
            return False
        
        print(f"✓ Found {len(image_dirs)} medicine samples")
        
        total_images = 0
        valid_images = 0
        
        for med_dir in sorted(image_dirs)[:15]:  # Check first 15
            images = list(med_dir.glob("*.jpg")) + list(med_dir.glob("*.png"))
            if images:
                print(f"\n  {med_dir.name}:")
                for img_path in images:
                    try:
                        img = Image.open(img_path)
                        width, height = img.size
                        size_mb = img_path.stat().st_size / (1024 * 1024)
                        
                        if width >= 800 and height >= 600:
                            status = "✓ VALID"
                            valid_images += 1
                        else:
                            status = f"⚠ TOO SMALL ({width}×{height})"
                        
                        print(f"    {img_path.name}: {width}×{height} ({size_mb:.2f}MB) {status}")
                        total_images += 1
                    except Exception as e:
                        print(f"    {img_path.name}: ✗ ERROR - {e}")
        
        if total_images == 0:
            print("\n✗ No valid images found")
            return False
        
        validity_ratio = valid_images / total_images if total_images > 0 else 0
        print(f"\n✓ Verification complete: {valid_images}/{total_images} images valid ({validity_ratio*100:.0f}%)")
        
        return validity_ratio > 0.8  # 80% valid is acceptable

def main():
    parser = argparse.ArgumentParser(
        description="MediShield Dataset Acquisition Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python acquire_dataset.py --source synthetic    # Create fake data (fastest)
  python acquire_dataset.py --source kaggle       # Try Kaggle API
  python acquire_dataset.py --auto               # Try Kaggle, fallback to synthetic
        """
    )
    parser.add_argument(
        "--source",
        choices=["kaggle", "synthetic", "auto"],
        default="auto",
        help="Data source (default: auto)"
    )
    parser.add_argument(
        "--count",
        type=int,
        default=15,
        help="Number of synthetic samples (default: 15)"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify existing dataset"
    )
    
    args = parser.parse_args()
    
    acq = DatasetAcquisition()
    
    if args.verify:
        acq.verify_dataset()
        return
    
    print("\n" + "="*70)
    print("MEDISHIELD DATASET ACQUISITION (PHASE 1)")
    print("="*70)
    print(f"Base directory: {acq.base_dir}")
    
    success = False
    
    if args.source in ["auto", "kaggle"]:
        print("\n[1/2] Attempting Kaggle download...")
        success = acq.try_kaggle_download()
        
        if success:
            print("\n✓ PHASE 1 COMPLETE: Kaggle dataset acquired")
        elif args.source == "kaggle":
            print("\n✗ Kaggle download failed and --source=kaggle specified")
            sys.exit(1)
    
    if not success and args.source in ["auto", "synthetic"]:
        print("\n[2/2] Falling back to synthetic generation...")
        success = acq.create_synthetic_dataset(num_samples=args.count)
    
    if success:
        print("\n" + "="*70)
        print("Step 1 Complete: Dataset Ready")
        print("="*70)
        acq.verify_dataset()
        
        print("\n" + "="*70)
        print("NEXT: Run baseline_test.py to compare old vs new OCR")
        print("="*70)
        print(f"\nCommand: python baseline_test.py --data-dir {acq.base_dir}")
    else:
        print("\n✗ Dataset acquisition failed")
        sys.exit(1)

if __name__ == "__main__":
    main()
