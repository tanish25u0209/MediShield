#!/usr/bin/env python3
"""
MediShield: Submission-Ready System
Judges can run this to test the complete OCR system.

Usage:
    python submit.py
"""

from pathlib import Path
from medishield_ocr import process_medicine_images
import json

def main():
    print("\n" + "="*80)
    print("MEDISHIELD - OCR EXTRACTION SYSTEM")
    print("="*80 + "\n")
    
    print("Testing on synthetic pharmaceutical dataset...\n")
    
    test_samples = [
        {
            "name": "Paracetamol 500mg",
            "images": [
                "medishield_data/raw/synthetic_01_paracetamol/front.jpg",
                "medishield_data/raw/synthetic_01_paracetamol/back.jpg"
            ]
        },
        {
            "name": "Aspirin 100mg",
            "images": [
                "medishield_data/raw/synthetic_02_aspirin/front.jpg",
                "medishield_data/raw/synthetic_02_aspirin/back.jpg"
            ]
        },
        {
            "name": "Amoxicillin 500mg",
            "images": [
                "medishield_data/raw/synthetic_03_amoxicillin/front.jpg",
                "medishield_data/raw/synthetic_03_amoxicillin/back.jpg"
            ]
        },
    ]
    
    results = []
    print(f"{'Sample':<25} {'Batch':<15} {'Expiry':<12} {'Name':<25}")
    print("-" * 77)
    
    for sample in test_samples:
        result = process_medicine_images(sample["images"])
        final = result["final_data"]
        
        batch = final.get("batch_number", "").strip() or "NOT FOUND"
        expiry = final.get("expiry_date", "").strip() or "NOT FOUND"
        name = final.get("medicine_name", "").strip() or "NOT FOUND"
        
        print(f"{sample['name']:<25} {batch:<15} {expiry:<12} {name:<25}")
        
        results.append({
            "sample": sample["name"],
            "batch_found": bool(batch != "NOT FOUND"),
            "expiry_found": bool(expiry != "NOT FOUND"),
            "batch": batch,
            "expiry": expiry,
            "name": name
        })
    
    print("-" * 77)
    
    # Summary
    batch_found = sum(1 for r in results if r["batch_found"])
    expiry_found = sum(1 for r in results if r["expiry_found"])
    
    print(f"\nSummary:")
    print(f"  Batch numbers found: {batch_found}/{len(results)} ({batch_found/len(results)*100:.0f}%)")
    print(f"  Expiry dates found:  {expiry_found}/{len(results)} ({expiry_found/len(results)*100:.0f}%)")
    
    print("\n" + "="*80)
    print("System Status: READY FOR JUDGES")
    print("="*80 + "\n")
    
    return 0

if __name__ == "__main__":
    exit(main())
