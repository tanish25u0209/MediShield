#!/usr/bin/env python3
"""
MediShield: Submission-Ready System
Judges can run this to test the complete unified pipeline.

Usage:
    python submit.py
"""

from medishield_pipeline import process_medicine
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
    print(f"{'Sample':<25} {'Verdict':<12} {'Conf':<8} {'Top reason':<45}")
    print("-" * 95)
    
    for sample in test_samples:
        result = process_medicine(sample["images"])
        final = result.get("final_output", {}) or {}
        verdict = str(final.get("FINAL_VERDICT", "SUSPICIOUS") or "SUSPICIOUS")
        confidence = str(final.get("CONFIDENCE_SCORE", 0) or 0)
        reasons = final.get("TOP_3_REASONS", []) or []
        top_reason = str(reasons[0]) if reasons else "No decisive reason available"

        print(f"{sample['name']:<25} {verdict:<12} {confidence:<8} {top_reason:<45}")

        results.append({
            "sample": sample["name"],
            "verdict": verdict,
            "confidence": confidence,
            "top_reason": top_reason,
        })
    
    print("-" * 95)
    
    # Summary
    high_risk = sum(1 for r in results if r["verdict"] == "HIGH_RISK")
    suspicious = sum(1 for r in results if r["verdict"] == "SUSPICIOUS")
    safe = sum(1 for r in results if r["verdict"] == "SAFE")
    
    print(f"\nSummary:")
    print(f"  SAFE:        {safe}/{len(results)} ({safe/len(results)*100:.0f}%)")
    print(f"  SUSPICIOUS:  {suspicious}/{len(results)} ({suspicious/len(results)*100:.0f}%)")
    print(f"  HIGH_RISK:   {high_risk}/{len(results)} ({high_risk/len(results)*100:.0f}%)")
    
    print("\n" + "="*80)
    print("System Status: READY FOR JUDGES")
    print("="*80 + "\n")
    
    return 0

if __name__ == "__main__":
    exit(main())
